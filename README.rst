trio_catcher
============

A context manager/decorator-based approach for catching multiple concurrent exceptions
as raised by trio's nurseries.

Documentation and an example of the usage pattern can be found in the docstrings.


Considerations
--------------

Just some considerations that came up while writing the catcher.


Why this Approach?
~~~~~~~~~~~~~~~~~~

Well, it's the cleanest I could find. :)

No, seriously, when compared to try/except, it requires the same number of levels
of indentation - exactly one. This can be achieved by registering handlers before
entering the with block.

Other than that, the semantics and naming are similar to those of try/except so that
it should be relatively easy to understand the concept.


Alternative Approaches
~~~~~~~~~~~~~~~~~~~~~~

Comparison to trio/exceptiongroup#5
___________________________________

Another decorator-based approach was suggested by @njsmith in `this issue
<https://github.com/python-trio/exceptiongroup/issues/5>`_. Here are some points in
which trio_catcher differs from this implementation:

* Multiple exceptions can be handled separately in a single ``with`` block without nesting.
* A handler is called multiple times if multiple exceptions of a type the handler
  was registered for were caught. This can be disabled by passing ``once=True``
  at handler registration time.
* Each handler can catch multiple exceptions (of same or different type) at once. This
  allows handling semantically-linked exceptions together. A handler is only called
  if all the exception types it requires are present.
  **This requires the experimental variant in the except-multiple branch! In the
  master branch, only one exception can be caught at a time.**
* Each handler can return any number of exceptions to be re-raised after exception
  handling is over.
  **This requires the experimental variant in except-multiple branch! With the master
  branch, at most one exception may be returned.**
* A handler can stop exception handling and swallow all exceptions by returning
  ``True``, as known from ``__exit__``.
* When a handler (re-)raises an exception, that immediately propagates out of the
  ``with`` block and replaces any still unhandled exception + those returned by
  handlers already executed.
* It supports both sync and async code for exception handling.
* It uses no predicate functions. Exceptions are selected solely by type and the
  handler can then implement further checks, if necessary. Whether this is an
  advantage is probably arguable, but I find it more clear to embed the predicate
  logic in the handlers.
* With normal ``try``/``except``, you can also have ``else`` and ``finally``
  branches. When you need these together with exception handling, you would need
  another ``try``/``finally`` outside the catch block, requiring one more indentation
  level. And even then, you could have no ``else`` branch, because that would run
  even if there were exceptions that were swallowed by your handler. With this
  implementation, however, else and finally handlers can be registered on the
  ``AsyncCatcher`` directly, not requiring a ``try`` block at all.


``with`` blocks as exception handlers
_____________________________________

First, I wanted to use normal try/except BaseException and with blocks for the
individual error handlers. However, this doesn't work because there is no sane way
for __enter__() to skip the exception of the block. It's possible with some nasty
hacks, but that's not bearable for something so fundamental as exception handling.


Manual Programmatic Handling
____________________________

TBD, but could be promising as well


Performance
~~~~~~~~~~~

Could be better.

This probably is due to the amount of function calling (decorators, handler
registration, enter/exit of the context manager, type checking, handler execution)
when compared to a plain try/except.

After all, I think the impact of this is negligible when something like nurseries
and task switching are in place anyway, but it surely needs serious profiling.


Handling MultiError/ExceptionGroup only
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When switching to ExceptionGroup which don't collapse, the whole catcher should
probably not handle plain exceptions at all and only be used when a nursery is
involved.


Coupling Catcher and Nursery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maybe the catcher API should simply be available on a Nursery directly? This would save
another with block/level of indentation. Afaik, nurseries are the only thing producing
multiple concurrent exceptions by design, so this seems reasonable to me at least.

Of course, the catcher should be usable without nursery as well if one wants to
catch the ExceptionGroup raised by a nursery somewhere higher in the call stack.

Technically, ``Nursery`` could create an ``AsyncCatcher`` at initialization
and just call its ``__aenter__``/``__aexit__`` methods from its own, basically
providing two with blocks in one. The user would then register handlers like so::

    async with trio.open_nursery() as nursery:
        @nursery.catcher.except_(ValueError)
        ...


Is the Sync Implementation Really Needed?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AsyncCatcher supports both sync and async handlers, and I can't think of a situation
in which you would need to catch a MultiError outside of an async function anyway, so
maybe there should only be one Catcher class which provides the ``async with`` variant.
