"""Live Production Collection Runner Verification for OpenPost.

Imports `postman_echo.json` and `github_api.json`, executes all requests
through `mcp_server.run_collection()`, and prints a detailed test execution report.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import mcp_server

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_collections"


async def main() -> None:
    print("=" * 70)
    print("OPENPOST LIVE PRODUCTION COLLECTION RUNNER")
    print("=" * 70)

    # 1. Create a live testing environment
    env = mcp_server.save_environment(
        name="Live Production Sandbox",
        variables={
            "app_name": "OpenPost",
            "target_owner": "google",
            "target_repo": "gson",
        },
    )
    env_id = env["id"]
    print(f"\n[1] Environment initialized: '{env['name']}' (ID: {env_id})")

    # 2. Import Postman Echo Suite
    echo_path = SAMPLES_DIR / "postman_echo.json"
    echo_imp = mcp_server.import_postman_collection(file_path=str(echo_path))
    echo_col_id = echo_imp["collection_id"]
    print(f"\n[2] Imported Collection: '{echo_imp['name']}' (Requests: {echo_imp['request_count']}, Folders: {echo_imp['folder_count']})")

    # 3. Import GitHub Suite
    gh_path = SAMPLES_DIR / "github_api.json"
    gh_imp = mcp_server.import_postman_collection(file_path=str(gh_path))
    gh_col_id = gh_imp["collection_id"]
    print(f"\n[3] Imported Collection: '{gh_imp['name']}' (Requests: {gh_imp['request_count']}, Folders: {gh_imp['folder_count']})")

    # 4. Execute Postman Echo Collection Runner
    print(f"\n" + "-" * 70)
    print(f"RUNNING: '{echo_imp['name']}' against postman-echo.com...")
    print("-" * 70)
    echo_results = await mcp_server.run_collection(
        collection_id=echo_col_id,
        environment_id=env_id,
        timeout_seconds=20.0,
    )

    for run in echo_results["runs"]:
        status_symbol = "[PASS]" if run["passed"] else "[FAIL]"
        print(f"\n{status_symbol} {run['method']} {run['name']}")
        print(f"       URL: {run['url']}")
        print(f"       Status: {run['status_code']} | Latency: {run['elapsed_ms']} ms")
        for test in run.get("test_results", []):
            t_sym = "  + pm.test:" if test["passed"] else "  x pm.test:"
            print(f"     {t_sym} {test['name']} -> {'PASSED' if test['passed'] else 'FAILED: ' + str(test['error'])}")

    print(f"\nEcho Suite Summary: {echo_results['passed']}/{echo_results['total_requests']} requests passed in {echo_results['total_elapsed_ms']} ms")

    # 5. Execute GitHub REST API Collection Runner
    print(f"\n" + "-" * 70)
    print(f"RUNNING: '{gh_imp['name']}' against api.github.com...")
    print("-" * 70)
    gh_results = await mcp_server.run_collection(
        collection_id=gh_col_id,
        environment_id=env_id,
        timeout_seconds=20.0,
    )

    for run in gh_results["runs"]:
        status_symbol = "[PASS]" if run["passed"] else "[FAIL]"
        print(f"\n{status_symbol} {run['method']} {run['name']}")
        print(f"       URL: {run['url']}")
        print(f"       Status: {run['status_code']} | Latency: {run['elapsed_ms']} ms")
        for test in run.get("test_results", []):
            t_sym = "  + pm.test:" if test["passed"] else "  x pm.test:"
            print(f"     {t_sym} {test['name']} -> {'PASSED' if test['passed'] else 'FAILED: ' + str(test['error'])}")

    print(f"\nGitHub Suite Summary: {gh_results['passed']}/{gh_results['total_requests']} requests passed in {gh_results['total_elapsed_ms']} ms")

    # 6. Verify environment mutations persisted across runs
    final_env = mcp_server.get_environment(env_id)
    print(f"\n" + "=" * 70)
    print("ENVIRONMENT VARIABLES EXTRACTED BY SCRIPTS DURING RUNS:")
    print("=" * 70)
    for v in final_env["variables"]:
        print(f"  * {v['key']} = {v['value']}")


if __name__ == "__main__":
    asyncio.run(main())
