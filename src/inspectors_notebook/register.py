"""Registers the relay as a native messaging host with each browser, for this user only.

    inspectors-notebook-register install
    inspectors-notebook-register uninstall

Chrome, Edge and Chromium allow the extension by origin, Firefox by add-on ID (NFR-5).
The installer (S5) will do the same with its own relay path.
"""

import argparse
import json
import os
import sys
import winreg
from pathlib import Path
from typing import Protocol

from .relay import HOST_NAME

# Fixed by the "key" in extension/src/manifest.json; tests check the two agree.
CHROMIUM_EXTENSION_ID = "ekjdcglidekbodkolhakfhleobcjidag"
FIREFOX_EXTENSION_ID = "{52724e34-54e6-4e08-bebb-ad98a8877daa}"

BROWSERS = {
    "chrome": (r"Software\Google\Chrome\NativeMessagingHosts", "chromium"),
    "edge": (r"Software\Microsoft\Edge\NativeMessagingHosts", "chromium"),
    "chromium": (r"Software\Chromium\NativeMessagingHosts", "chromium"),
    "firefox": (r"Software\Mozilla\NativeMessagingHosts", "firefox"),
}
DESCRIPTION = "Inspector's Notebook relay"


class Registry(Protocol):
    def set_default(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class UserRegistry:
    """HKEY_CURRENT_USER, so no admin rights are needed."""

    def set_default(self, key: str, value: str) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)

    def delete(self, key: str) -> None:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def host_manifests(relay_path: Path) -> dict[str, dict]:
    base = {"name": HOST_NAME, "description": DESCRIPTION, "path": str(relay_path), "type": "stdio"}
    return {
        "chromium": {**base, "allowed_origins": [f"chrome-extension://{CHROMIUM_EXTENSION_ID}/"]},
        "firefox": {**base, "allowed_extensions": [FIREFOX_EXTENSION_ID]},
    }


def default_folder() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "InspectorsNotebook" / "native-messaging"


def default_relay_path() -> Path:
    return Path(sys.executable).parent / "inspectors-notebook-relay.exe"


def install(relay_path: Path, folder: Path, registry: Registry) -> dict[str, Path]:
    if not relay_path.is_file():
        raise FileNotFoundError(f"Relay not found at {relay_path}")
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for flavour, manifest in host_manifests(relay_path).items():
        files[flavour] = folder / f"{HOST_NAME}.{flavour}.json"
        files[flavour].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for key, flavour in BROWSERS.values():
        registry.set_default(rf"{key}\{HOST_NAME}", str(files[flavour]))
    return files


def uninstall(folder: Path, registry: Registry) -> None:
    for key, _ in BROWSERS.values():
        registry.delete(rf"{key}\{HOST_NAME}")
    for flavour in ("chromium", "firefox"):
        (folder / f"{HOST_NAME}.{flavour}.json").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the relay with Chrome, Edge, Chromium and Firefox.")
    parser.add_argument("action", choices=["install", "uninstall"])
    args = parser.parse_args()
    if args.action == "install":
        relay_path = default_relay_path()
        install(relay_path, default_folder(), UserRegistry())
        print(f"Registered {relay_path} for {', '.join(BROWSERS)}")
    else:
        uninstall(default_folder(), UserRegistry())
        print("Unregistered the relay")


if __name__ == "__main__":
    main()
