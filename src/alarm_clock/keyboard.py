"""Single-keypress terminal input.

The live UI has to redraw the clock roughly four times a second *and*
stay responsive to keys, so it can't sit in a blocking ``input()``.
This puts the terminal in cbreak mode and offers a ``read`` with a
timeout, which is what lets the main loop do both.
"""

from __future__ import annotations

import contextlib
import os
import select
import sys
import termios
import time
import tty
from types import TracebackType
from typing import Any, Iterator, Optional, TextIO, Type


#: How long to wait for the rest of an escape sequence. Arrow keys send
#: three bytes at once; a lone Esc sends one and nothing follows.
ESCAPE_WAIT_SECONDS = 0.03

_ESCAPES = {
    "\x1b[A": "up",
    "\x1bOA": "up",
    "\x1b[B": "down",
    "\x1bOB": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1b[3~": "delete",
}


def decode_escape(data: bytes) -> str:
    """Name an escape sequence: 'up', 'down', ... or 'esc' for a bare Esc."""
    return _ESCAPES.get(data.decode(errors="ignore"), "esc" if data == b"\x1b" else "unknown")


class KeyReader:
    """Reads one key at a time, with a timeout, restoring the tty after.

    Used as a context manager. On a stream that isn't a terminal (a
    pipe, a test harness) it degrades to "no keys ever arrive" rather
    than raising, so callers can decide what to do without guarding
    every call.
    """

    def __init__(self, stream: Optional[TextIO] = None) -> None:
        self._stream: TextIO = stream if stream is not None else sys.stdin
        self._saved: Optional[Any] = None  # opaque termios attribute list

    @property
    def is_terminal(self) -> bool:
        try:
            return self._stream.isatty()
        except (AttributeError, ValueError):
            return False

    def __enter__(self) -> "KeyReader":
        self._set_cbreak()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self._restore()

    def _set_cbreak(self) -> None:
        if not self.is_terminal:
            return
        fd = self._stream.fileno()
        self._saved = termios.tcgetattr(fd)
        # cbreak rather than raw: keys arrive unbuffered, but Ctrl+C
        # still raises SIGINT, so the usual way out keeps working.
        tty.setcbreak(fd)

    def _restore(self) -> None:
        if self._saved is None:
            return
        termios.tcsetattr(self._stream.fileno(), termios.TCSADRAIN, self._saved)
        self._saved = None

    def read(self, timeout: float) -> Optional[str]:
        """The next keypress, or None if ``timeout`` elapsed first."""
        if not self.is_terminal:
            time.sleep(timeout)
            return None
        ready, _, _ = select.select([self._stream], [], [], timeout)
        if not ready:
            return None
        fd = self._stream.fileno()
        data = os.read(fd, 1)
        if data == b"\x1b":
            return decode_escape(data + self._drain(fd, 8))
        if data and data[0] >= 0xC0:
            # The lead byte of a multi-byte UTF-8 character (an accented
            # letter in a label): fetch the rest so it isn't dropped.
            extra = 1 if data[0] < 0xE0 else 2 if data[0] < 0xF0 else 3
            data += self._drain(fd, extra)
        return data.decode(errors="ignore") or None

    def _drain(self, fd: int, limit: int) -> bytes:
        """Whatever bytes follow immediately, up to ``limit``."""
        extra = b""
        while len(extra) < limit:
            ready, _, _ = select.select([self._stream], [], [], ESCAPE_WAIT_SECONDS)
            if not ready:
                break
            extra += os.read(fd, 1)
            if len(extra) >= 2 and (extra[-1:].isalpha() or extra[-1:] == b"~"):
                break  # end of an escape sequence
        return extra

    @contextlib.contextmanager
    def paused(self) -> Iterator[None]:
        """Drop back to normal line input, e.g. to ask a question."""
        self._restore()
        try:
            yield
        finally:
            self._set_cbreak()
