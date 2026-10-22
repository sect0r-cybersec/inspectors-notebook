import subprocess
import sys


def run(folder, body: str) -> None:
    """In a fresh interpreter: logging and the hang dump are process-wide."""
    script = f"import time\nfrom pathlib import Path\nfrom inspectors_notebook import diagnostics\n{body}"
    subprocess.run([sys.executable, "-c", script, str(folder)], check=True, timeout=30)


def test_a_normal_start_logs_and_leaves_no_hang_file(tmp_path):
    run(tmp_path, "diagnostics.start(Path(__import__('sys').argv[1]))\nimport logging\nlogging.getLogger('x').info('Docked')\ndiagnostics.started()")
    log = (tmp_path / "inspectors-notebook.log").read_text(encoding="utf-8")
    assert "INFO inspectors_notebook.diagnostics: Starting" in log and "INFO x: Docked" in log
    assert list(tmp_path.glob("startup-hang-*.txt")) == []


def test_a_slow_start_dumps_every_threads_stack(tmp_path):
    run(tmp_path, "diagnostics.start(Path(__import__('sys').argv[1]), limit=0.2)\n\ndef stuck_here():\n    time.sleep(1)\n\nstuck_here()\ndiagnostics.started()")
    [dump] = tmp_path.glob("startup-hang-*.txt")
    text = dump.read_text(encoding="utf-8")
    assert "Timeout (0:00:00.200000)!" in text and "in stuck_here" in text


def test_leaving_before_startup_finishes_tidies_up(tmp_path):
    run(tmp_path, "diagnostics.start(Path(__import__('sys').argv[1]))")  # a second launch returns early
    assert list(tmp_path.glob("startup-hang-*.txt")) == []


def test_a_crashed_thread_is_logged(tmp_path):
    run(tmp_path, "import threading\ndiagnostics.start(Path(__import__('sys').argv[1]))\n"
        "t = threading.Thread(target=lambda: 1 / 0, name='bridge')\nt.start()\nt.join()\ndiagnostics.started()")
    log = (tmp_path / "inspectors-notebook.log").read_text(encoding="utf-8")
    assert "ERROR inspectors_notebook.diagnostics: Uncaught exception in thread bridge" in log and "ZeroDivisionError" in log
