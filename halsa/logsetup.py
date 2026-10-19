"""Multi-process-safe rotating file handler.

Python's RotatingFileHandler is not safe when several processes write
the same file (gunicorn master + workers, Django workers): after one
process rotates, the others keep writing to the renamed inode and their
records vanish. This subclass notices the inode changed underneath it
and reopens the path, so every writer follows the rotation.
"""

import logging
import logging.handlers
import os


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dev_ino = self._stat()

    def _stat(self):
        try:
            st = os.fstat(self.stream.fileno())
            return (st.st_dev, st.st_ino)
        except (AttributeError, OSError, ValueError):
            return None

    def reopen_if_rotated(self):
        current = None
        try:
            st = os.stat(self.baseFilename)
            current = (st.st_dev, st.st_ino)
        except OSError:
            pass  # file deleted; recreate below
        if current != self._dev_ino:
            self.acquire()
            try:
                if self.stream:
                    try:
                        self.stream.close()
                    except OSError:
                        pass
                    self.stream = None
                self.stream = self._open()
                self._dev_ino = self._stat()
            finally:
                self.release()

    def emit(self, record):
        try:
            self.reopen_if_rotated()
        except OSError:
            pass
        super().emit(record)

    def doRollover(self):
        super().doRollover()
        self._dev_ino = self._stat()
