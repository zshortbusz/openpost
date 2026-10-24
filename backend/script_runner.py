"""Bridge for executing Postman pre-request and test scripts in a sandboxed Node.js environment."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

SANDBOX_SCRIPT_PATH = Path(__file__).resolve().parent / "script_sandbox.js"


def get_node_executable() -> str | None:
    """Find system Node.js binary path."""
    return shutil.which("node")


def extract_scripts_from_events(
    events: list[dict[str, Any]] | None,
    listen_type: str,
) -> list[str]:
    """Extract JavaScript source code from collection or request event arrays."""
    if not events:
        return []

    scripts: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("listen", "")).lower() == listen_type.lower():
            script_node = ev.get("script", {})
            if isinstance(script_node, dict):
                exec_val = script_node.get("exec", "")
                if isinstance(exec_val, list):
                    scripts.append("\n".join(str(line) for line in exec_val))
                elif isinstance(exec_val, str) and exec_val.strip():
                    scripts.append(exec_val)
    return scripts


async def run_postman_script_async(
    script: str,
    listen: str = "test",
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
    collection_variables: dict[str, str] | None = None,
    globals_dict: dict[str, str] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Execute a Postman script asynchronously in the Node.js sandbox."""
    node_bin = get_node_executable()
    if not node_bin:
        return {
            "ok": False,
            "error": "Node.js executable not found in PATH.",
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": ["[WARN] Node.js not installed; scripts skipped."],
        }

    input_payload = {
        "script": script,
        "listen": listen,
        "request": request or {},
        "response": response,
        "environment": environment or {},
        "collection_variables": collection_variables or {},
        "globals": globals_dict or {},
    }

    try:
        proc = await asyncio.create_subprocess_exec(
            node_bin,
            str(SANDBOX_SCRIPT_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        input_bytes = json.dumps(input_payload).encode("utf-8")
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(input_bytes),
            timeout=timeout_seconds,
        )

        if stdout_data:
            return json.loads(stdout_data.decode("utf-8", errors="replace"))

        return {
            "ok": False,
            "error": stderr_data.decode("utf-8", errors="replace") or "Empty sandbox output",
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": [],
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {
            "ok": False,
            "error": f"Script execution timed out after {timeout_seconds}s",
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": [],
        }


def run_postman_script_sync(
    script: str,
    listen: str = "test",
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
    collection_variables: dict[str, str] | None = None,
    globals_dict: dict[str, str] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Execute a Postman script synchronously in the Node.js sandbox."""
    node_bin = get_node_executable()
    if not node_bin:
        return {
            "ok": False,
            "error": "Node.js executable not found in PATH.",
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": ["[WARN] Node.js not installed; scripts skipped."],
        }

    input_payload = {
        "script": script,
        "listen": listen,
        "request": request or {},
        "response": response,
        "environment": environment or {},
        "collection_variables": collection_variables or {},
        "globals": globals_dict or {},
    }

    try:
        proc = subprocess.run(
            [node_bin, str(SANDBOX_SCRIPT_PATH)],
            input=json.dumps(input_payload).encode("utf-8"),
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )

        if proc.stdout:
            return json.loads(proc.stdout.decode("utf-8", errors="replace"))

        return {
            "ok": False,
            "error": proc.stderr.decode("utf-8", errors="replace") or "Empty sandbox output",
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "test_results": [],
            "updated_environment": environment or {},
            "updated_collection_variables": collection_variables or {},
            "logs": [],
        }
