"""OpenPost Model Context Protocol (MCP) Server.

Exposes 100% of Postman's core functionality as structured MCP tools so AI agents
can operate OpenPost autonomously without requiring human UI interaction.

Tool Categories:
1. Collections (Import, Export v2.1.0, List, Get, Create, Delete)
2. Request & Folder Authoring (Create Folder, Save/Update Request, Delete Request)
3. Request Execution & Collection Runner (Send Ad-hoc Request, Run Saved Request,
   Run Full Collection / Folder, Preview Variable Interpolation, Execute Postman Script)
4. Environments & Variables (List, Get, Save Environment, Set/Delete Variable, Delete Environment)
5. History & Auditing (List History, Get Full History Entry, Clear History)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as _MCPServerClass
except ImportError:
    from mcp.server.fastmcp import FastMCP as _MCPServerClass  # type: ignore[no-redef]

from backend.collection_parser import parse_postman_collection_file
from backend.local_db import LocalStore
from backend.request_engine import (
    build_variable_context,
    execute_http_request,
    prepare_http_request,
)
from backend.script_runner import (
    extract_scripts_from_events,
    run_postman_script_async,
)

mcp = _MCPServerClass("OpenPost")
_store: LocalStore | None = None


def get_store() -> LocalStore:
    global _store
    if _store is None:
        _store = LocalStore()
    return _store


def set_store(store: LocalStore) -> None:
    """Allow tests or custom runners to inject a specific LocalStore instance."""
    global _store
    _store = store


def _is_active_auth(auth: dict[str, Any] | None) -> bool:
    """Return True if an auth block defines a non-noauth authentication scheme."""
    return bool(isinstance(auth, dict) and auth.get("type") and str(auth.get("type")).lower() != "noauth")


def _resolve_effective_auth(
    target_req: dict[str, Any],
    col: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve effective auth with precedence: Request > Folder (deepest to shallowest) > Collection."""
    req_auth = target_req.get("auth")
    if _is_active_auth(req_auth):
        return req_auth

    if col:
        req_folder_path = list(target_req.get("folder_path") or [])
        if req_folder_path and col.get("folders"):
            folder_lookup: dict[tuple[str, ...], dict[str, Any]] = {}
            for f in col.get("folders", []):
                if isinstance(f, dict) and f.get("name"):
                    f_full_path = tuple(list(f.get("folder_path") or []) + [str(f["name"])])
                    folder_lookup[f_full_path] = f

            for depth in range(len(req_folder_path), 0, -1):
                prefix = tuple(req_folder_path[:depth])
                folder_node = folder_lookup.get(prefix)
                if folder_node and _is_active_auth(folder_node.get("auth")):
                    return folder_node["auth"]

        col_auth = col.get("auth")
        if _is_active_auth(col_auth):
            return col_auth

    return req_auth


# ============================================================================
# 1. COLLECTION TOOLS
# ============================================================================


@mcp.tool()
def import_postman_collection(
    file_path: str | None = None,
    collection_json: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Import a Postman Collection v2.1.0 or OpenPost native JSON from a local file path or raw JSON payload."""
    store = get_store()
    if file_path:
        in_path = Path(file_path)
        if in_path.suffix.lower() != ".json":
            raise ValueError("Collection file path must have a .json extension.")
        parsed = parse_postman_collection_file(in_path)
        saved = store.save_collection(parsed)
    elif collection_json is not None:
        raw = json.loads(collection_json) if isinstance(collection_json, str) else collection_json
        saved = store.import_postman_json(raw)
    else:
        raise ValueError("Provide either `file_path` or `collection_json`.")

    return {
        "status": "imported",
        "collection_id": saved["id"],
        "name": saved["name"],
        "folder_count": len(saved.get("folders", [])),
        "request_count": len(saved.get("requests", [])),
        "variable_count": len(saved.get("variables", [])),
    }


@mcp.tool()
def export_postman_collection(
    collection_id: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Export an OpenPost collection back to standard Postman Collection v2.1.0 JSON format."""
    store = get_store()
    exported = store.export_collection_v21(collection_id)
    if not exported:
        raise KeyError(f"Collection not found: {collection_id}")

    if output_path:
        out = Path(output_path)
        if ".." in out.parts or out.suffix.lower() != ".json":
            raise ValueError("Output path must be a valid .json file path without parent directory traversal ('..').")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(exported, indent=2), encoding="utf-8")
        return {"status": "exported", "output_path": str(out), "collection": exported}

    return {"status": "exported", "collection": exported}


@mcp.tool()
def list_collections() -> list[dict[str, Any]]:
    """List all local collections with folder, request, and variable counts."""
    return get_store().list_collections()


@mcp.tool()
def get_collection(collection_id: str) -> dict[str, Any]:
    """Retrieve the complete structure (folders, requests, variables, auth) of a collection."""
    col = get_store().get_collection(collection_id)
    if not col:
        raise KeyError(f"Collection not found: {collection_id}")
    return col


@mcp.tool()
def create_collection(
    name: str,
    description: str = "",
    variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new local collection."""
    return get_store().create_collection(name=name, description=description, variables=variables)


@mcp.tool()
def delete_collection(collection_id: str) -> dict[str, Any]:
    """Delete a collection from local storage."""
    deleted = get_store().delete_collection(collection_id)
    return {"collection_id": collection_id, "deleted": deleted}


# ============================================================================
# 2. REQUEST & FOLDER AUTHORING TOOLS (CRUD)
# ============================================================================


@mcp.tool()
def create_folder(
    collection_id: str,
    name: str,
    parent_folder_path: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Create a folder (`item-group`) inside a collection."""
    return get_store().add_folder(
        collection_id=collection_id,
        name=name,
        parent_folder_path=parent_folder_path,
        description=description,
    )


@mcp.tool()
def save_request(
    collection_id: str,
    name: str,
    method: str,
    raw_url: str,
    request_id: str | None = None,
    folder_path: list[str] | None = None,
    headers: list[dict[str, Any]] | None = None,
    query_params: list[dict[str, Any]] | None = None,
    body: dict[str, Any] | None = None,
    auth: dict[str, Any] | None = None,
    description: str = "",
    events: list[dict[str, Any]] | None = None,
    path_variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or update (`Ctrl+S` equivalent) an HTTP request inside a collection."""
    return get_store().upsert_request(
        collection_id=collection_id,
        name=name,
        method=method,
        raw_url=raw_url,
        request_id=request_id,
        folder_path=folder_path,
        headers=headers,
        query_params=query_params,
        body=body,
        auth=auth,
        description=description,
        events=events,
        path_variables=path_variables,
    )


@mcp.tool()
def delete_request(collection_id: str, request_id: str) -> dict[str, Any]:
    """Delete a saved request from a collection."""
    deleted = get_store().delete_request(collection_id=collection_id, request_id=request_id)
    return {"collection_id": collection_id, "request_id": request_id, "deleted": deleted}


# ============================================================================
# 3. REQUEST EXECUTION, INTERPOLATION & COLLECTION RUNNER TOOLS
# ============================================================================


@mcp.tool()
def interpolate_preview(
    raw_url: str,
    method: str = "GET",
    headers: list[dict[str, Any]] | dict[str, str] | None = None,
    query_params: list[dict[str, Any]] | dict[str, str] | None = None,
    body: dict[str, Any] | str | None = None,
    auth: dict[str, Any] | None = None,
    collection_id: str | None = None,
    environment_id: str | None = None,
    override_variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Dry-run preview of URL, headers, params, and body after resolving `{{variables}}`."""
    store = get_store()
    col_vars = []
    if collection_id:
        col = store.get_collection(collection_id)
        if col:
            col_vars = col.get("variables", [])

    env_vars = []
    if environment_id:
        env = store.get_environment(environment_id)
        if env:
            env_vars = [
                {"key": v["key"], "value": v["value"], "disabled": not v.get("enabled", True)}
                for v in env.get("variables", [])
            ]

    merged_vars = build_variable_context(
        collection_vars=col_vars,
        environment_vars=env_vars,
        override_vars=override_variables,
    )
    return prepare_http_request(
        method=method,
        raw_url=raw_url,
        headers=headers,
        query_params=query_params,
        body=body,
        auth=auth,
        variables=merged_vars,
    )


@mcp.tool()
async def send_request(
    method: str,
    raw_url: str,
    headers: list[dict[str, Any]] | dict[str, str] | None = None,
    query_params: list[dict[str, Any]] | dict[str, str] | None = None,
    body: dict[str, Any] | str | None = None,
    auth: dict[str, Any] | None = None,
    environment_id: str | None = None,
    override_variables: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
    collection_id: str | None = None,
) -> dict[str, Any]:
    """Send an ad-hoc HTTP request (Scratch Pad mode), interpolate variables, and log to SQLite history."""
    store = get_store()
    col_vars = []
    col_auth = None
    if collection_id:
        col = store.get_collection(collection_id)
        if col:
            col_vars = col.get("variables", [])
            col_auth = col.get("auth")

    env_vars = []
    if environment_id:
        env = store.get_environment(environment_id)
        if env:
            env_vars = [
                {"key": v["key"], "value": v["value"], "disabled": not v.get("enabled", True)}
                for v in env.get("variables", [])
            ]

    effective_auth = auth if (auth and auth.get("type", "noauth") != "noauth") else (col_auth or auth)
    merged_vars = build_variable_context(
        collection_vars=col_vars,
        environment_vars=env_vars,
        override_vars=override_variables,
    )
    result = await execute_http_request(
        method=method,
        raw_url=raw_url,
        headers=headers,
        query_params=query_params,
        body=body,
        auth=effective_auth,
        variables=merged_vars,
        timeout_seconds=timeout_seconds,
    )
    history_entry = store.record_history(
        method=method,
        url=result["url"],
        status_code=result["status_code"],
        elapsed_ms=result["elapsed_ms"],
        size_bytes=result["size_bytes"],
        request_data=result["prepared_request"],
        response_data={
            "status_code": result["status_code"],
            "headers": result["headers"],
            "body_text": result["body_text"],
        },
        collection_id=collection_id,
    )
    result["history_id"] = history_entry["id"]
    return result


@mcp.tool()
async def run_collection_request(
    collection_id: str,
    request_id: str,
    environment_id: str | None = None,
    override_variables: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
    request_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a specific saved request from a collection with full scope variable resolution."""
    store = get_store()
    col = store.get_collection(collection_id)
    if not col:
        raise KeyError(f"Collection not found: {collection_id}")

    saved_req = next((r for r in col.get("requests", []) if r.get("id") == request_id), None)
    if not saved_req:
        raise KeyError(f"Request {request_id} not found in collection {collection_id}")

    target_req = dict(saved_req)
    if request_overrides:
        for k, v in request_overrides.items():
            if v is not None:
                target_req[k] = v

    env_vars = []
    env_obj = None
    if environment_id:
        env_obj = store.get_environment(environment_id)
        if env_obj:
            env_vars = [
                {"key": v["key"], "value": v["value"], "disabled": not v.get("enabled", True)}
                for v in env_obj.get("variables", [])
            ]

    current_env = {v["key"]: str(v["value"]) for v in env_vars if not v.get("disabled", False)}
    current_col_vars = {
        v.get("key", ""): str(v.get("value", ""))
        for v in col.get("variables", [])
        if not v.get("disabled", False) and v.get("key")
    }
    initial_env = dict(current_env)
    initial_col_vars = dict(current_col_vars)

    # 1. Execute Pre-request Scripts
    prerequest_scripts = (
        extract_scripts_from_events(col.get("raw_events"), "prerequest")
        + extract_scripts_from_events(target_req.get("events"), "prerequest")
    )
    for pr_script in prerequest_scripts:
        pr_res = await run_postman_script_async(
            script=pr_script,
            listen="prerequest",
            request={"url": target_req.get("raw_url", ""), "method": target_req.get("method", "GET")},
            environment=current_env,
            collection_variables=current_col_vars,
        )
        if pr_res.get("ok"):
            current_env = dict(pr_res.get("updated_environment", current_env))
            current_col_vars = dict(pr_res.get("updated_collection_variables", current_col_vars))

    merged_vars = build_variable_context(
        collection_vars=[{"key": k, "value": v} for k, v in current_col_vars.items()],
        environment_vars=[{"key": k, "value": v} for k, v in current_env.items()],
        override_vars=override_variables,
    )
    result = await execute_http_request(
        method=target_req.get("method", "GET"),
        raw_url=target_req.get("raw_url", ""),
        headers=target_req.get("headers", []),
        query_params=target_req.get("query_params", []),
        path_variables=target_req.get("path_variables"),
        body=target_req.get("body"),
        auth=_resolve_effective_auth(target_req, col),
        variables=merged_vars,
        timeout_seconds=timeout_seconds,
    )

    # 2. Execute Test Scripts
    test_scripts = (
        extract_scripts_from_events(col.get("raw_events"), "test")
        + extract_scripts_from_events(target_req.get("events"), "test")
    )
    test_results = []
    for t_script in test_scripts:
        t_res = await run_postman_script_async(
            script=t_script,
            listen="test",
            request={"url": result.get("url"), "method": target_req.get("method", "GET")},
            response=result,
            environment=current_env,
            collection_variables=current_col_vars,
        )
        test_results.extend(t_res.get("test_results", []))
        if t_res.get("ok"):
            current_env = dict(t_res.get("updated_environment", current_env))
            current_col_vars = dict(t_res.get("updated_collection_variables", current_col_vars))

    result["test_results"] = test_results
    if environment_id and env_obj and current_env != initial_env:
        disabled_env_vars = [
            v for v in env_obj.get("variables", []) if not v.get("enabled", True) and v.get("key") not in current_env
        ]
        updated_env_list = [
            {"key": k, "value": v, "enabled": True} for k, v in current_env.items()
        ] + disabled_env_vars
        store.save_environment(name=env_obj["name"], variables=updated_env_list, env_id=environment_id)

    if current_col_vars != initial_col_vars:
        disabled_col_vars = [
            v for v in col.get("variables", []) if v.get("disabled", False) and v.get("key") not in current_col_vars
        ]
        col["variables"] = [
            {"key": k, "value": v, "type": "string", "disabled": False} for k, v in current_col_vars.items()
        ] + disabled_col_vars
        store.save_collection(col)
    history_entry = store.record_history(
        method=target_req.get("method", "GET"),
        url=result["url"],
        status_code=result["status_code"],
        elapsed_ms=result["elapsed_ms"],
        size_bytes=result["size_bytes"],
        request_data=result["prepared_request"],
        response_data={
            "status_code": result["status_code"],
            "headers": result["headers"],
            "body_text": result["body_text"],
        },
        collection_id=collection_id,
        request_id=request_id,
    )
    result["history_id"] = history_entry["id"]
    result["request_name"] = target_req.get("name")
    return result


@mcp.tool()
async def run_collection(
    collection_id: str,
    folder_filter: list[str] | None = None,
    environment_id: str | None = None,
    override_variables: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Collection Runner: sequentially execute all requests in a collection (or subfolder)."""
    store = get_store()
    col = store.get_collection(collection_id)
    if not col:
        raise KeyError(f"Collection not found: {collection_id}")

    requests_to_run = col.get("requests", [])
    if folder_filter:
        requests_to_run = [
            r
            for r in requests_to_run
            if r.get("folder_path", [])[: len(folder_filter)] == folder_filter
        ]

    results = []
    passed = 0
    failed = 0
    total_ms = 0.0

    for req in requests_to_run:
        res = await run_collection_request(
            collection_id=collection_id,
            request_id=req["id"],
            environment_id=environment_id,
            override_variables=override_variables,
            timeout_seconds=timeout_seconds,
        )
        tests_passed = all(t.get("passed", True) for t in res.get("test_results", []))
        is_success = bool(res.get("ok") and 200 <= int(res.get("status_code", 0)) < 400 and tests_passed)
        if is_success:
            passed += 1
        else:
            failed += 1
        total_ms += float(res.get("elapsed_ms", 0.0))
        results.append(
            {
                "request_id": req["id"],
                "name": req.get("name"),
                "method": req.get("method"),
                "url": res.get("url"),
                "status_code": res.get("status_code"),
                "elapsed_ms": res.get("elapsed_ms"),
                "passed": is_success,
                "test_results": res.get("test_results", []),
                "history_id": res.get("history_id"),
            }
        )

    return {
        "collection_id": collection_id,
        "collection_name": col.get("name"),
        "total_requests": len(results),
        "passed": passed,
        "failed": failed,
        "total_elapsed_ms": round(total_ms, 2),
        "runs": results,
    }


@mcp.tool()
async def execute_postman_script(
    script: str,
    listen: str = "test",
    request_data: dict[str, Any] | None = None,
    response_data: dict[str, Any] | None = None,
    environment_id: str | None = None,
    override_variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute arbitrary Postman JavaScript (testing pm.expect assertions or variable mutations)."""
    store = get_store()
    env_vars = {}
    if environment_id:
        env_obj = store.get_environment(environment_id)
        if env_obj:
            env_vars = {
                v["key"]: str(v["value"])
                for v in env_obj.get("variables", [])
                if v.get("enabled", True) and v.get("key")
            }
    if override_variables:
        env_vars.update(override_variables)

    return await run_postman_script_async(
        script=script,
        listen=listen,
        request=request_data,
        response=response_data,
        environment=env_vars,
    )


# ============================================================================
# 4. ENVIRONMENT & VARIABLE MANAGEMENT TOOLS
# ============================================================================


@mcp.tool()
def list_environments() -> list[dict[str, Any]]:
    """List all environments stored in OpenPost."""
    return get_store().list_environments()


@mcp.tool()
def get_environment(environment_id: str) -> dict[str, Any]:
    """Retrieve a specific environment and its variables."""
    env = get_store().get_environment(environment_id)
    if not env:
        raise KeyError(f"Environment not found: {environment_id}")
    return env


@mcp.tool()
def save_environment(
    name: str,
    variables: list[dict[str, Any]] | dict[str, Any],
    environment_id: str | None = None,
) -> dict[str, Any]:
    """Create or update an environment variable set."""
    return get_store().save_environment(name=name, variables=variables, env_id=environment_id)


@mcp.tool()
def set_environment_variable(
    environment_id: str,
    key: str,
    value: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Set, update, or delete (when `value=None`) a single variable in an environment."""
    return get_store().set_environment_variable(
        env_id=environment_id,
        key=key,
        value=value,
        enabled=enabled,
    )


@mcp.tool()
def delete_environment(environment_id: str) -> dict[str, Any]:
    """Delete an environment from SQLite storage."""
    deleted = get_store().delete_environment(environment_id)
    return {"environment_id": environment_id, "deleted": deleted}


# ============================================================================
# 5. HISTORY TOOLS
# ============================================================================


@mcp.tool()
def list_request_history(limit: int = 50) -> list[dict[str, Any]]:
    """List recent HTTP request executions from SQLite history."""
    return get_store().list_history(limit=limit)


@mcp.tool()
def get_history_entry(history_id: str) -> dict[str, Any]:
    """Get full request and response details for a specific history entry."""
    entry = get_store().get_history_entry(history_id)
    if not entry:
        raise KeyError(f"History entry not found: {history_id}")
    return entry


@mcp.tool()
def clear_request_history() -> dict[str, Any]:
    """Clear all entries from the local SQLite request history."""
    count = get_store().clear_history()
    return {"cleared_entries": count}

if __name__ == "__main__":
    mcp.run()
