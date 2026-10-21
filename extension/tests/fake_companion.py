"""Stands in for the companion during extension tests.

Serves the real user-only pipe, answers each hello the way the companion's bridge
does, and prints every message it receives as a JSON line. Exits when stdin closes.
"""

import json
import os
import sys
import threading

from inspectors_notebook import pipe

_print_lock = threading.Lock()


def emit(message: dict) -> None:
    with _print_lock:
        print(json.dumps(message), flush=True)


def serve_client(conn: pipe.Connection) -> None:
    try:
        while True:
            message = conn.receive()
            emit(message)
            if message.get("type") == "hello":
                conn.send({"type": "status", "recording": False})
    except pipe.PipeError:
        pass


def main() -> None:
    server = pipe.Server(pipe.default_pipe_name())
    try:
        server.listen()
    except pipe.AlreadyRunning:
        emit({"fake": "already_running"})
        sys.exit(2)
    threading.Thread(target=lambda: (sys.stdin.read(), os._exit(0)), daemon=True).start()
    emit({"fake": "ready"})
    while (conn := server.accept()) is not None:
        threading.Thread(target=serve_client, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
