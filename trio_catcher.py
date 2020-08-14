import functools
import inspect

import attr
import trio


def _nested_types_repr(types):
    """Recursively generate string repr for (nested) tuples of :class:`type` objects."""
    reprs = []
    for _type in types:
        if isinstance(_type, tuple):
            reprs.append(_nested_types_repr(_type))
        elif _type.__module__ == "builtins":
            reprs.append(_type.__qualname__)
        else:
            reprs.append(f"{_type.__module__}.{_type.__qualname__}")
    return f"({', '.join(reprs)})"


@attr.s(eq=False, slots=True)
class CatcherBase:
    """
    Common functionality of :class:`AsyncCatcher` and :class:`Catcher`, such as
    handler registration.
    """

    _exc_handlers = attr.ib(
        factory=list,
        init=False,
        repr=lambda l: _nested_types_repr(item[0] for item in l),
    )
    _else_handlers = attr.ib(factory=list, init=False, repr=lambda l: str(len(l)))
    _finally_handlers = attr.ib(factory=list, init=False, repr=lambda l: str(len(l)))
    _state = attr.ib(
        default=0, init=False, repr={0: "unused", 1: "entered", 2: "exited"}.get
    )

    def _check_registrable(self, handler):
        if self._state == 2:
            raise RuntimeError(
                "No more handlers can be registered after the catcher was exited"
            )

    def else_(self, handler):
        """Add a callable to run when the ``with`` block exits without exception.

        This corresponds to the ``else`` branch of a ``try`` block.

        The handler will run before eventual finally handlers. It is called with no
        arguments and its return value is ignored.

        Else handlers are executed in the order they were added. If one of them
        raises an exception, that exception is re-raised outside the ``with`` block
        and any subsequent else handler will be skipped. However, finally handlers
        will run anyway.
        """
        self._check_registrable(handler)
        self._else_handlers.append(handler)
        return handler

    def except_(self, *exc_type, once=False):
        """Add a callable for handling some type(s) of exception.

        When multiple tasks are involved, they can possibly all raise an exception at
        once, which trio collects into a :exc:`trio.MultiError`. The catcher allows
        each single exception to be handled at a time and, possibly, to replace
        and/or re-raise some of them to the outer scope.

        When one or more exceptions are raised inside the catcher's ``with`` block,
        exception handling kicks in, which works as follows:

        Each exception caught from the ``with`` block may be handled separately by
        a handler previously registered using :meth:`except_`. The order in which
        exceptions are handled is unspecified, but handlers are always considered in
        the order they were added. For each handler/exception pair, it is checked
        whether the handler is responsible for the type of exception. The first
        matching handler wins and gets called with the :exc:`BaseException` object
        it should handle as the only argument.

        After it handled the exception, the handler must perform one of these four
        actions:

        * If it returns ``None``, the exception is dropped and the next one is handled,
          if any.
        * If it returns ``True``, all exceptions are dropped and the ``with`` block
          exits without raising anything.
        * If it returns an :exc:`BaseException` object (can also be the one
          originally passed in for handling), the original exception is replaced by
          the returned and handling continues with the next exception.
        * If it re-raises the exception it should handle or raises another one,
          that exception immediately propagates out of the ``with`` block. Remaining
          exceptions are dropped.

        After the last handler ran through, all still unconsumed exceptions and
        the ones returned by handlers are re-raised outside the ``with`` block. If,
        however, none is left, the block exits without exception.

        No matter what happens during exception handling, afterwards, the registered
        finally handlers are executed.

        .. note::

           If you need to register different handlers for a type of exception and one
           of its sub-types (e.g. :exc`OSError` and :exc:`ConnectionResetError`),
           register the handler for the sub-type (:exc:`ConnectionResetError`)
           first, because otherwise the handler for :exc:`OSError` would catch them
           both. This is the same as with native ``except`` blocks.

        .. note::

            At the moment, the catcher doesn't allow handling a whole caught
            :exc:`trio.MultiError` at once. If such an exception is caught by the
            catcher, it is always unrolled and the individual exceptions handled
            individually. However, if that multi-error contains other multi-errors
            (as produced by nested nurseries), these are kept as they are and can
            be handled just like any other exception.

            This situation could improve with the upcoming ExceptionGroup, as
            they can also contain just a single exception and don't unwrap it like
            :exc:`MultiError` does.

        :param exc_type: type of exception or tuple of alternative exceptions to handle
        :type  exc_type: type, (type)
        :param once:
            When ``True``, the handler is only executed once - for the first
            exception that matches ``exc_type`` and not considered for further
            concurrent exceptions.
            This is a keyword-only argument.
        :type  once: bool
        """

        # Verify types are correct and no type follows one of its supertypes
        prev_types = None
        for types in exc_type:
            if not isinstance(types, tuple):
                types = (types,)
            for _type in types:
                if not isinstance(_type, type) or not issubclass(_type, BaseException):
                    raise TypeError(f"{_type} is no subclass of BaseException")
            if prev_types is not None:
                for prev in prev_types:
                    for cur in types:
                        if issubclass(cur, prev):
                            raise RuntimeError(
                                f"{cur!r} may not be given after its supertype {prev!r}"
                            )
            prev_types = types

        def _register(handler):
            self._check_registrable(handler)
            self._exc_handlers.append((exc_type, handler, once))
            return handler

        return _register

    def finally_(self, handler):
        """Add a callable to run finally, regardless of eventual exceptions.

        This corresponds to the ``finally`` branch of a ``try`` block.

        The handler will be executed after eventual exception or else handlers ran,
        no matter if they raised something themselves or not. It is called with no
        arguments and its return value is ignored.

        Finally handlers are executed in the order they were added. If one of them
        raises an exception, that exception propagates out of the ``with`` block
        and any subsequent handler will be skipped.
        """
        self._check_registrable(handler)
        self._finally_handlers.append(handler)
        return handler


class AsyncCatcher(CatcherBase):
    """
    Async-capable catcher. Both synchronous and asynchronous functions can be
    registered as handlers.

    Use like so::

        catcher = AsyncCatcher()

        @catcher.except_(ValueError)
        def _(exc):
            print("handled", repr(exc))
            # Drop the exception by returning None

        # Only handle the first Cancelled and keep the others
        @catcher.except_(trio.Cancelled, once=True)
        async def _(exc):
            print("cancellation intercepted, sleeping for a second")
            with trio.CancelScope(shield=True):
                await trio.sleep(1)
            print("done")
            # Keep exception intact and re-raise it after all exceptions were handled
            return exc

        @catcher.finally_
        def _():
            print("finally")

        with trio.CancelScope() as cscope:
            async with catcher:
                async with trio.open_nursery() as nursery:
                    # Start a background task
                    async def task():
                        await trio.sleep_forever()

                    nursery.start_soon(task)

                    # We can add another finally handler, even from inside the catcher
                    @catcher.finally_
                    def _():
                        print("finally 2")

                    # Cancel the whole nursery from outside
                    cscope.cancel()

                    # This raises the ValueError + 2x trio.Cancelled (one from task()
                    # and one from the nursery's main task)
                    raise ValueError
    """

    __slots__ = ()

    async def __aenter__(self):
        if self._state != 0:
            raise RuntimeError("AsyncCatcher can only be entered once")
        self._state = 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._state = 2
        try:
            if exc is None:
                for handler in self._else_handlers:
                    if inspect.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
                return

            orig_exc = exc
            excs = set(exc.exceptions) if isinstance(exc, trio.MultiError) else {exc}
            orig_excs = frozenset(excs)
            repl = []
            for types, handler, once in self._exc_handlers:
                # Consume exceptions until the handler doesn't fit anymore
                while excs:
                    matching_excs = []
                    for _type in types:
                        for _exc in excs:
                            if isinstance(_exc, _type):
                                matching_excs.append(_exc)
                                break
                        else:
                            matching_excs = None
                            break
                    if not matching_excs:
                        # Continue with next handler
                        break
                    excs.difference_update(matching_excs)
                    if inspect.iscoroutinefunction(handler):
                        result = await handler(*matching_excs)
                    else:
                        result = handler(*matching_excs)
                    if result is True:
                        # Drop all exceptions and exit
                        return True
                    if result is None:
                        result = ()
                    elif isinstance(result, BaseException):
                        result = (result,)
                    elif isinstance(result, tuple) and any(
                        not isinstance(item, BaseException) for item in result
                    ):
                        raise RuntimeError(
                            f"{handler!r} for {matching_excs} returned illegal {result}"
                        )
                    repl.append((matching_excs, result))
                    if once:
                        # Proceed with next handler
                        break

            if repl:
                # Build a new MultiError with the remaining exceptions
                remaining_excs = set(orig_excs)
                for matching_excs, replacements in repl:
                    remaining_excs.difference_update(matching_excs)
                    remaining_excs.update(replacements)
                if not remaining_excs:
                    # All exceptions handled; leave the with block cleanly
                    return True
                exc = trio.MultiError(list(remaining_excs))
                # Re-raise remaining exception outside the with block; set original
                # exception as cause
                raise exc from orig_exc

            # Not altered, re-raise original
            return

        finally:
            for handler in self._finally_handlers:
                try:
                    if inspect.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
                except BaseException as _exc:
                    # Decouple __context__ of exception in finally phase from the
                    # original exception raised inside the with block
                    raise _exc from None


class Catcher(CatcherBase):
    """
    A catcher. Only synchronous functions can be registered as handlers.

    See :class:`AsyncCatcher` for details on how the catcher works. The only
    difference is that :class:`Catcher` has to be entered using ``with`` instead of
    ``async with``.
    """

    __slots__ = ()

    def __enter__(self):
        if self._state != 0:
            raise RuntimeError("Catcher can only be entered once")
        self._state = 1
        return self

    def __exit__(self, exc_type, exc, tb):
        # TODO:
        # The implementation is identical to that of AsyncCatcher, except for the
        # iscoroutinefunction() checks. It could be copied over once the details
        # are fixed.
        raise NotImplementedError("Use AsyncCatcher for now")

    def _check_registrable(self, handler):
        super()._check_registrable(handler)
        if inspect.iscoroutinefunction(handler):
            raise RuntimeError(
                "Tried to register async handler with Catcher; use AsyncCatcher instead"
            )
