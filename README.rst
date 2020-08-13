trio_catcher
============

A context manager/decorator-based approach for catching multiple concurrent exceptions
as raised by trio's nurseries.

Documentation and an example of the usage pattern can be found in the docstrings.


Considerations
--------------

Just some considerations that came up while writing the catcher.


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
