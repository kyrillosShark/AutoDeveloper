# cleanup.py

import atexit
import shutil
import os
import tempfile
import logging
from execution import terminate_process

def cleanup():
    # Terminate subprocesses and clean temporary directories
    terminate_process()
    session_dir = os.path.join(tempfile.gettempdir(), "compiler_session")
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)
    logging.debug("Cleaned up temporary files and processes.")

atexit.register(cleanup)

