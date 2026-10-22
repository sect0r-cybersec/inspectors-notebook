"""The app's log file and startup hang dump. Local files only; nothing is sent anywhere.

The panel is a windowed program with no console, so without a file its log is lost.
If startup takes longer than STARTUP_LIMIT, every thread's stack is written to
startup-hang-<pid>.txt beside the log, which shows where it is stuck even inside a
call into .NET or WebView2. The log holds app events (browsers connecting, shell and
shortcut problems), never captured page text or queries.
"""

import atexit
import faulthandler
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

log = logging.getLogger(__name__)

STARTUP_LIMIT = 20  # seconds; a cold start of the installed app takes about 6 s on a CI runner
LOG_BYTES = 1_000_000

_hang: TextIO | None = None


def default_folder() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "InspectorsNotebook" / "logs"


def start(folder: Path | None = None, limit: float = STARTUP_LIMIT) -> None:
    """Log to a file and arm the hang dump. Called once, as early as possible; later calls do nothing."""
    global _hang
    if _hang is not None:
        return
    folder = folder or default_folder()
    folder.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(folder / "inspectors-notebook.log", maxBytes=LOG_BYTES, backupCount=1, encoding="utf-8")
    ]
    if sys.stderr:  # None in the packaged, windowed app
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(levelname)s %(name)s: %(message)s", handlers=handlers)
    # Python prints these to stderr, which the packaged app doesn't have.
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_in_thread
    _hang = open(folder / f"startup-hang-{os.getpid()}.txt", "w", encoding="utf-8")
    faulthandler.dump_traceback_later(limit, file=_hang)
    atexit.register(started)
    log.info("Starting")


def _log_uncaught(kind, error, tb) -> None:
    log.critical("Uncaught exception", exc_info=(kind, error, tb))


def _log_uncaught_in_thread(args: threading.ExceptHookArgs) -> None:
    name = args.thread.name if args.thread else "?"
    log.error("Uncaught exception in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def started() -> None:
    """Startup finished (or the process is leaving): disarm, and drop the dump file if nothing was written."""
    global _hang
    if _hang is None or _hang.closed:
        return
    faulthandler.cancel_dump_traceback_later()
    path = Path(_hang.name)
    _hang.close()
    if path.stat().st_size == 0:
        path.unlink()
