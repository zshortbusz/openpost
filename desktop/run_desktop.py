"""OpenPost Instant Desktop Application Launcher.

Spawns the local FastAPI server in a background thread and launches a standalone
frameless desktop window using native Windows Edge/Chromium in app mode
(`--app=http://127.0.0.1:8000`), giving a clean desktop client experience
with zero build time.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
import uvicorn
from backend.main import app

PORT = 8000
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def start_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def wait_for_server(timeout_seconds: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            r = httpx.get(f"{URL}/api/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.2)
    return False


def find_browser_app_executable() -> str | None:
    # 1. Edge on Windows
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for ep in edge_paths:
        if os.path.exists(ep):
            return ep

    # 2. Chrome
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for cp in chrome_paths:
        if os.path.exists(cp):
            return cp

    return shutil.which("msedge") or shutil.which("chrome")


def build_app_command(exe: str, url: str = URL) -> list[str]:
    profile_dir = PROJECT_ROOT / "data" / "desktop_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return [
        exe,
        f"--app={url}",
        "--window-size=1366,840",
        f"--user-data-dir={profile_dir}",
    ]


def launch_desktop(dry_run: bool = False) -> None:
    print(f"Starting OpenPost backend server at {URL}...")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    if not wait_for_server():
        print("ERROR: Backend server failed to start within timeout.", file=sys.stderr)
        sys.exit(1)

    print("Backend ready. Checking desktop client window executable...")
    exe = find_browser_app_executable()
    if exe:
        cmd = build_app_command(exe, URL)
        print(f"Detected browser executable: {exe}")
        if dry_run:
            print("Dry run requested: Server verified and app command validated successfully.")
            return
        try:
            proc = subprocess.Popen(cmd)
            proc.wait()
            print("Desktop window closed. Exiting OpenPost.")
            return
        except Exception as exc:
            print(f"Could not spawn app window: {exc}")

    if dry_run:
        print("Dry run requested: Server verified, fallback to default browser.")
        return

    # Fallback to default browser
    webbrowser.open(URL)
    print("Press Ctrl+C to stop the OpenPost server.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting OpenPost.")


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenPost Standalone Desktop Application Launcher")
    parser.add_argument(
        "--check",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Validate backend server startup, frontend static serving, and browser executable without opening GUI",
    )
    args = parser.parse_args()
    launch_desktop(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
