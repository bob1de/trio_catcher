#!/usr/bin/env python

import trio
from trio_catcher import AsyncCatcher


async def main():
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


trio.run(main)
