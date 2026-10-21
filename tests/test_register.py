import base64
import hashlib
import json
from pathlib import Path

import pytest

from inspectors_notebook import register
from inspectors_notebook.relay import HOST_NAME

EXTENSION_MANIFEST = Path(__file__).parents[1] / "extension" / "src" / "manifest.json"


class FakeRegistry:
    def __init__(self):
        self.values = {}

    def set_default(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def relay_exe(tmp_path):
    exe = tmp_path / "bin" / "inspectors-notebook-relay.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    return exe


def test_install_writes_manifests_and_registers_every_browser(tmp_path, relay_exe):
    reg = FakeRegistry()
    files = register.install(relay_exe, tmp_path / "nm", reg)

    chromium = json.loads(files["chromium"].read_text(encoding="utf-8"))
    assert chromium == {
        "name": HOST_NAME,
        "description": register.DESCRIPTION,
        "path": str(relay_exe),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{register.CHROMIUM_EXTENSION_ID}/"],
    }
    firefox = json.loads(files["firefox"].read_text(encoding="utf-8"))
    assert firefox["allowed_extensions"] == [register.FIREFOX_EXTENSION_ID]
    assert "allowed_origins" not in firefox

    assert reg.values == {
        rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}": str(files["chromium"]),
        rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}": str(files["chromium"]),
        rf"Software\Chromium\NativeMessagingHosts\{HOST_NAME}": str(files["chromium"]),
        rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}": str(files["firefox"]),
    }


def test_host_name_is_valid_for_browsers():
    # Lowercase letters, digits, underscores and dots; no leading or trailing dot.
    assert all(c.islower() or c.isdigit() or c in "._" for c in HOST_NAME)
    assert not HOST_NAME.startswith(".") and not HOST_NAME.endswith(".")


def test_install_refuses_missing_relay(tmp_path):
    with pytest.raises(FileNotFoundError):
        register.install(tmp_path / "nope.exe", tmp_path / "nm", FakeRegistry())


def test_uninstall_removes_keys_and_files(tmp_path, relay_exe):
    reg = FakeRegistry()
    files = register.install(relay_exe, tmp_path / "nm", reg)
    register.uninstall(tmp_path / "nm", reg)
    assert reg.values == {}
    assert not any(f.exists() for f in files.values())
    register.uninstall(tmp_path / "nm", reg)  # idempotent


def test_extension_ids_match_the_extension_manifest():
    manifest = json.loads(EXTENSION_MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(c, 16)) for c in digest) == register.CHROMIUM_EXTENSION_ID
    assert manifest["browser_specific_settings"]["gecko"]["id"] == register.FIREFOX_EXTENSION_ID
