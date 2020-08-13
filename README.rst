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

First, I wanted to use normal try/except BaseException and with blocks for the
individual error handlers. However, this doesn't work because there is no sane way
for __enter__() to skip the exception of the block. It's possible with some nasty
hacks, but that's not bearable for something so fundamental as exception handling.


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
