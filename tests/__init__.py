from __future__ import annotations

import os
import tempfile


if os.name == "nt":
    _temporary_directory = tempfile.TemporaryDirectory

    class WindowsTemporaryDirectory(_temporary_directory):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("ignore_cleanup_errors", True)
            super().__init__(*args, **kwargs)

    tempfile.TemporaryDirectory = WindowsTemporaryDirectory
