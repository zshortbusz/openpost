"""Tests for OpenPost Standalone Desktop Application Distribution.

Verifies:
1. Tauri configuration (src-tauri/tauri.conf.json) schema and settings.
2. Desktop icon asset generation (icons/, icon.ico, icon.png, sizes).
3. Browser app window launcher resolution and command generation.
4. Desktop launcher --check / dry-run execution with FastAPI backend.
5. Serving of index.html and static assets in desktop window mode.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from backend.main import app
from desktop.run_desktop import (
    URL,
    build_app_command,
    find_browser_app_executable,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_TAURI_DIR = PROJECT_ROOT / "src-tauri"
ICONS_DIR = SRC_TAURI_DIR / "icons"


def test_find_browser_app_executable() -> None:
    exe = find_browser_app_executable()
    assert exe is not None, "A compatible Chromium/Edge browser executable must be found on Windows."
    assert os.path.exists(exe), f"Browser executable path does not exist on disk: {exe}"


def test_build_app_command() -> None:
    dummy_exe = r"C:\Windows\System32\notepad.exe"
    cmd = build_app_command(dummy_exe, URL)
    assert cmd[0] == dummy_exe
    assert cmd[1] == f"--app={URL}"
    assert "--window-size=1366,840" in cmd
    assert any(arg.startswith("--user-data-dir=") for arg in cmd)


def test_tauri_configuration_schema() -> None:
    conf_path = SRC_TAURI_DIR / "tauri.conf.json"
    assert conf_path.exists(), f"tauri.conf.json missing at {conf_path}"

    data = json.loads(conf_path.read_text(encoding="utf-8"))
    assert data.get("productName") == "OpenPost"
    assert data.get("version") == "0.1.0"
    assert data.get("identifier") == "com.openpost.desktop"

    # Build settings
    build_conf = data.get("build", {})
    assert build_conf.get("frontendDist") == "../frontend"
    assert "8000" in build_conf.get("devUrl", "")

    # Window settings
    windows = data.get("app", {}).get("windows", [])
    assert len(windows) >= 1
    main_win = windows[0]
    assert main_win.get("width") == 1366
    assert main_win.get("height") == 840
    assert "OpenPost" in main_win.get("title", "")

    # Bundle icons
    bundle = data.get("bundle", {})
    assert bundle.get("active") is True
    icons = bundle.get("icon", [])
    assert "icons/icon.ico" in icons
    assert "icons/128x128.png" in icons


def test_tauri_icon_assets_exist() -> None:
    assert ICONS_DIR.exists(), f"icons directory missing at {ICONS_DIR}"

    required_icons = [
        "32x32.png",
        "64x64.png",
        "128x128.png",
        "128x128@2x.png",
        "icon.ico",
        "icon.icns",
        "icon.png",
    ]

    for icon_name in required_icons:
        icon_path = ICONS_DIR / icon_name
        assert icon_path.exists(), f"Required desktop icon missing: {icon_path}"
        assert icon_path.stat().st_size > 0, f"Icon file is empty: {icon_path}"

    # Verify PNG signature (first 8 bytes)
    png_path = ICONS_DIR / "icon.png"
    png_bytes = png_path.read_bytes()
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "icon.png is not a valid PNG binary"

    # Verify ICO signature (first 4 bytes: 00 00 01 00)
    ico_path = ICONS_DIR / "icon.ico"
    ico_bytes = ico_path.read_bytes()
    assert ico_bytes[:4] == b"\x00\x00\x01\x00", "icon.ico is not a valid ICO binary"


def test_desktop_fastapi_frontend_serving() -> None:
    client = TestClient(app)

    # 1. Health check
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    # 2. Main Desktop UI index
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "<title>OpenPost — Local-First Agentic API Client</title>" in res_index.text
    assert 'class="brand-badge"' in res_index.text

    # 3. Static CSS
    res_css = client.get("/static/styles.css")
    assert res_css.status_code == 200
    assert "--bg-root: #0d0f14;" in res_css.text

    # 4. Static JS
    res_js = client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "OpenPost" in res_js.text

    # 5. Root-level static serving (for parity with embedded desktop webviews)
    res_root_css = client.get("/styles.css")
    assert res_root_css.status_code == 200
    assert "--bg-root: #0d0f14;" in res_root_css.text

    res_root_js = client.get("/app.js")
    assert res_root_js.status_code == 200
    assert "API_BASE" in res_root_js.text


def test_desktop_launcher_fallback_when_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop import run_desktop

    monkeypatch.setattr(run_desktop, "find_browser_app_executable", lambda: None)
    # In dry-run mode, this should complete cleanly without opening a GUI
    run_desktop.launch_desktop(dry_run=True)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "desktop" / "run_desktop.py"),
        "--check",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"run_desktop.py --check failed: {proc.stderr}"
    assert "Dry run requested: Server verified" in proc.stdout
    assert "Detected browser executable:" in proc.stdout


def test_desktop_launcher_dry_run_mode() -> None:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "desktop" / "run_desktop.py"),
        "--dry-run",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"run_desktop.py --dry-run failed: {proc.stderr}"
    assert "Dry run requested: Server verified" in proc.stdout


def test_compiled_desktop_binary_and_bundles() -> None:
    target_dir = SRC_TAURI_DIR / "target"
    debug_exe = target_dir / "debug" / "openpost.exe"
    release_exe = target_dir / "release" / "openpost.exe"
    assert debug_exe.exists() or release_exe.exists(), "At least one compiled openpost.exe binary must exist"

    exe_path = release_exe if release_exe.exists() else debug_exe
    assert exe_path.stat().st_size > 1_000_000, f"Binary size unexpectedly small: {exe_path.stat().st_size} bytes"

    # Check PE header magic (MZ)
    header = exe_path.read_bytes()[:2]
    assert header == b"MZ", "Target binary is not a valid Windows PE executable"

    # If release bundle exists, check installer files
    bundle_dir = target_dir / "release" / "bundle"
    if bundle_dir.exists():
        msi_files = list((bundle_dir / "msi").glob("*.msi")) if (bundle_dir / "msi").exists() else []
        nsis_files = list((bundle_dir / "nsis").glob("*.exe")) if (bundle_dir / "nsis").exists() else []
        assert len(msi_files) >= 1, "Expected WiX MSI installer bundle"
        assert len(nsis_files) >= 1, "Expected NSIS installer bundle"
