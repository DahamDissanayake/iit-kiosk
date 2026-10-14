"""Shared test setup."""

from core.bus import use_selector_loop_on_windows

# pyzmq's asyncio sockets need the selector event loop, which Windows does not use by default.
use_selector_loop_on_windows()
