# PyInstaller build in folder mode (NFR-9): the app, the relay and the register tool
# share one folder and one copy of the Python runtime.
#
#     uv run pyinstaller packaging/inspectors-notebook.spec --noconfirm
#
# Run through packaging/build.ps1, which draws the icon first and then builds the installer.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
launchers = Path(SPECPATH) / "launchers"
icon = str(root / "build" / "inspectors-notebook.ico")
# The panel's HTML, CSS and JavaScript, read through importlib.resources.
datas = collect_data_files("inspectors_notebook", includes=["ui/*"])

programs = [
    # (name, console): the relay and the register tool speak over stdin and stdout.
    ("inspectors-notebook", False),
    ("inspectors-notebook-relay", True),
    ("inspectors-notebook-register", True),
]

exes = []
collected = []
for name, console in programs:
    a = Analysis(
        [str(launchers / f"{name}.py")],
        pathex=[str(root / "src")],
        datas=datas if name == "inspectors-notebook" else [],
        noarchive=False,
    )
    exes.append(
        EXE(
            PYZ(a.pure),
            a.scripts,
            exclude_binaries=True,
            name=name,
            console=console,
            icon=icon,
            upx=False,
        )
    )
    collected += [a.binaries, a.datas]

COLLECT(*exes, *collected, upx=False, name="InspectorsNotebook")
