"""HTTP Dispatching & Variable String-Interpolation Engine.

Handles:
- Recursive resolution of `{{variable}}` placeholders across scopes:
  `Overrides > Environment > Collection > Built-in Dynamic Variables`
- Built-in Postman dynamic variables:
  - `{{$guid}}` / `{{$uuid}}`
  - `{{$timestamp}}`
  - `{{$isoTimestamp}}`
  - `{{$randomInt}}`
- Cycle/infinite-recursion protection for self-referencing variables.
- Auth header/query injection (`bearer`, `basic`, `apikey`).
- Asynchronous and synchronous HTTP request execution via `httpx`.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import random
import re
import string
import time
import uuid
from typing import Any

import httpx

VARIABLE_PATTERN = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")
PATH_VARIABLE_PATTERN = re.compile(r"(?<=/):([a-zA-Z0-9_]+)(?=[/?#]|$)")
MAX_INTERPOLATION_DEPTH = 5


def _resolve_dynamic_variable(var_name: str) -> str | None:
    """Resolve built-in Postman `$` dynamic variables."""
    if var_name in ("$guid", "$uuid", "$randomUUID"):
        return str(uuid.uuid4())
    if var_name == "$timestamp":
        return str(int(time.time()))
    if var_name == "$isoTimestamp":
        return dt.datetime.now(dt.timezone.utc).isoformat()
    if var_name == "$randomInt":
        return str(random.randint(0, 1000))
    if var_name == "$randomBoolean":
        return str(random.choice([True, False])).lower()
    if var_name == "$randomEmail":
        return f"user_{random.randint(100, 9999)}@example.com"
    if var_name == "$randomAlphaNumeric":
        return "".join(random.choices(string.ascii_letters + string.digits, k=10))
    if var_name == "$randomFirstName":
        return random.choice(["Alice", "Bob", "Charlie", "Diana", "Evan", "Fiona"])
    if var_name == "$randomLastName":
        return random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller"])
    return None


def build_variable_context(
    collection_vars: list[dict[str, Any]] | dict[str, Any] | None = None,
    environment_vars: list[dict[str, Any]] | dict[str, Any] | None = None,
    override_vars: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Merge variable scopes with priority: Overrides > Environment > Collection."""
    merged: dict[str, str] = {}

    def _ingest(source: list[dict[str, Any]] | dict[str, Any] | None) -> None:
        if not source:
            return
        if isinstance(source, dict):
            for k, v in source.items():
                if v is not None:
                    merged[str(k)] = str(v)
        elif isinstance(source, list):
            for item in source:
                if isinstance(item, dict) and not item.get("disabled", False):
                    k = item.get("key")
                    if k:
                        merged[str(k)] = "" if item.get("value") is None else str(item.get("value"))

    _ingest(collection_vars)
    _ingest(environment_vars)
    _ingest(override_vars)
    return merged


def interpolate_string(
    template: str,
    variables: dict[str, str],
    unresolved_out: set[str] | None = None,
) -> str:
    """Interpolate `{{var}}` tokens in `template` up to `MAX_INTERPOLATION_DEPTH` passes."""
    if not template or "{{" not in template:
        return template

    current = template
    for _ in range(MAX_INTERPOLATION_DEPTH):
        changed = False

        def _replacer(match: re.Match[str]) -> str:
            nonlocal changed
            var_name = match.group(1)
            if var_name.startswith("$"):
                dyn_val = _resolve_dynamic_variable(var_name)
                if dyn_val is not None:
                    changed = True
                    return dyn_val

            if var_name in variables:
                replacement = str(variables[var_name])
                if replacement != match.group(0):
                    changed = True
                return replacement

            if unresolved_out is not None:
                unresolved_out.add(var_name)
            return match.group(0)

        next_str = VARIABLE_PATTERN.sub(_replacer, current)
        current = next_str
        if not changed or "{{" not in current:
            break

    # Final scan to record any remaining unresolved placeholders
    if unresolved_out is not None:
        for match in VARIABLE_PATTERN.finditer(current):
            var_name = match.group(1)
            if not var_name.startswith("$") and var_name not in variables:
                unresolved_out.add(var_name)

    return current


def interpolate_url(
    raw_url: str,
    variables: dict[str, str],
    unresolved_out: set[str] | None = None,
) -> str:
    """Interpolate both `:pathVariables` and `{{variables}}` in URLs."""
    current = raw_url
    if ":" in current:
        def _path_replacer(match: re.Match[str]) -> str:
            param_name = match.group(1)
            if param_name in variables:
                return str(variables[param_name])
            return match.group(0)

        current = PATH_VARIABLE_PATTERN.sub(_path_replacer, current)

    resolved = interpolate_string(current, variables, unresolved_out)
    return resolved


def interpolate_structure(
    data: Any,
    variables: dict[str, str],
    unresolved_out: set[str] | None = None,
) -> Any:
    """Recursively interpolate strings inside dicts, lists, or primitives."""
    if isinstance(data, str):
        return interpolate_string(data, variables, unresolved_out)
    if isinstance(data, list):
        return [interpolate_structure(item, variables, unresolved_out) for item in data]
    if isinstance(data, dict):
        return {
            interpolate_string(str(k), variables, unresolved_out): interpolate_structure(
                v, variables, unresolved_out
            )
            for k, v in data.items()
        }
    return data


def prepare_http_request(
    method: str,
    raw_url: str,
    headers: list[dict[str, Any]] | dict[str, str] | None = None,
    query_params: list[dict[str, Any]] | dict[str, str] | None = None,
    path_variables: list[dict[str, Any]] | None = None,
    body: dict[str, Any] | str | None = None,
    auth: dict[str, Any] | None = None,
    variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve all variables, apply auth headers/params, and return a ready-to-dispatch request spec."""
    var_map = dict(variables or {})
    unresolved: set[str] = set()
    if path_variables:
        for pv in path_variables:
            if isinstance(pv, dict):
                k = pv.get("key")
                v = pv.get("value")
                if k and v is not None and str(k) not in var_map:
                    var_map[str(k)] = interpolate_string(str(v), var_map, unresolved)

    resolved_url = interpolate_url(raw_url.strip(), var_map, unresolved)

    # Normalize & interpolate headers
    final_headers: dict[str, str] = {}
    if isinstance(headers, dict):
        for k, v in headers.items():
            rk = interpolate_string(str(k), var_map, unresolved)
            rv = interpolate_string(str(v), var_map, unresolved)
            if rk:
                final_headers[rk] = rv
    elif isinstance(headers, list):
        for h in headers:
            if isinstance(h, dict) and not h.get("disabled", False):
                rk = interpolate_string(str(h.get("key", "")), var_map, unresolved)
                rv = interpolate_string(str(h.get("value", "")), var_map, unresolved)
                if rk:
                    final_headers[rk] = rv

    # Normalize & interpolate explicit query params
    final_params: list[tuple[str, str]] = []
    if isinstance(query_params, dict):
        for k, v in query_params.items():
            rk = interpolate_string(str(k), var_map, unresolved)
            rv = interpolate_string(str(v), var_map, unresolved)
            if rk:
                final_params.append((rk, rv))
    elif isinstance(query_params, list):
        for q in query_params:
            if isinstance(q, dict) and not q.get("disabled", False):
                rk = interpolate_string(str(q.get("key", "")), var_map, unresolved)
                rv = interpolate_string(str(q.get("value", "")), var_map, unresolved)
                if rk:
                    final_params.append((rk, rv))

    # Avoid duplicating query params if they are already identically present in `resolved_url`
    if "?" in resolved_url and final_params:
        base_part, _ = resolved_url.split("?", 1)
        resolved_url = base_part

    # Inject Auth
    if auth and isinstance(auth, dict):
        auth_type = str(auth.get("type", "noauth")).lower()
        params = interpolate_structure(auth.get("params", {}), var_map, unresolved)
        if auth_type == "bearer":
            token = params.get("token", "")
            if token:
                final_headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            username = params.get("username", "")
            password = params.get("password", "")
            encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            final_headers["Authorization"] = f"Basic {encoded}"
        elif auth_type == "apikey":
            key_name = params.get("key", "")
            key_val = params.get("value", "")
            where = params.get("in", "header")
            if key_name:
                if where == "query":
                    final_params.append((key_name, key_val))
                else:
                    final_headers[key_name] = key_val

    # Prepare body
    content_bytes: bytes | None = None
    form_data: dict[str, str] | None = None
    if isinstance(body, str) and body:
        resolved_body_str = interpolate_string(body, var_map, unresolved)
        content_bytes = resolved_body_str.encode("utf-8")
    elif isinstance(body, dict) and not body.get("disabled", False):
        mode = body.get("mode", "raw")
        if mode == "raw":
            raw_text = interpolate_string(str(body.get("raw", "")), var_map, unresolved)
            if raw_text:
                content_bytes = raw_text.encode("utf-8")
                if (
                    body.get("language") == "json"
                    and not any(k.lower() == "content-type" for k in final_headers)
                ):
                    final_headers["Content-Type"] = "application/json"
        elif mode in ("urlencoded", "formdata"):
            form_data = {}
            for entry in body.get(mode, []) or []:
                if isinstance(entry, dict) and not entry.get("disabled", False):
                    ek = interpolate_string(str(entry.get("key", "")), var_map, unresolved)
                    ev = interpolate_string(str(entry.get("value", "")), var_map, unresolved)
                    if ek:
                        form_data[ek] = ev
        elif mode == "graphql":
            gql = interpolate_structure(body.get("graphql", {}), var_map, unresolved)
            content_bytes = json.dumps(gql).encode("utf-8")
            if not any(k.lower() == "content-type" for k in final_headers):
                final_headers["Content-Type"] = "application/json"

    return {
        "method": method.upper(),
        "url": resolved_url,
        "headers": final_headers,
        "params": final_params,
        "content": content_bytes.decode("utf-8", errors="replace") if content_bytes else None,
        "form_data": form_data,
        "unresolved_variables": sorted(unresolved),
    }


async def execute_http_request(
    method: str,
    raw_url: str,
    headers: list[dict[str, Any]] | dict[str, str] | None = None,
    query_params: list[dict[str, Any]] | dict[str, str] | None = None,
    path_variables: list[dict[str, Any]] | None = None,
    body: dict[str, Any] | str | None = None,
    auth: dict[str, Any] | None = None,
    variables: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
    follow_redirects: bool = True,
) -> dict[str, Any]:
    """Interpolate variables and dispatch an HTTP request using `httpx.AsyncClient`."""
    prepared = prepare_http_request(
        method=method,
        raw_url=raw_url,
        headers=headers,
        query_params=query_params,
        path_variables=path_variables,
        body=body,
        auth=auth,
        variables=variables,
    )

    start_ns = time.perf_counter_ns()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
            verify=False,
        ) as client:
            kwargs: dict[str, Any] = {
                "method": prepared["method"],
                "url": prepared["url"],
                "headers": prepared["headers"],
            }
            if prepared["params"]:
                kwargs["params"] = prepared["params"]
            if prepared["form_data"] is not None:
                kwargs["data"] = prepared["form_data"]
            elif prepared["content"] is not None:
                kwargs["content"] = prepared["content"].encode("utf-8")

            response = await client.request(**kwargs)
            elapsed_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 2)

            resp_headers = dict(response.headers)
            content_type = resp_headers.get("content-type", "")
            raw_text = response.text
            parsed_json = None
            if "json" in content_type.lower():
                try:
                    parsed_json = response.json()
                except Exception:
                    parsed_json = None

            return {
                "ok": True,
                "status_code": response.status_code,
                "reason_phrase": response.reason_phrase,
                "elapsed_ms": elapsed_ms,
                "size_bytes": len(response.content),
                "url": str(response.url),
                "headers": resp_headers,
                "body_text": raw_text,
                "body_json": parsed_json,
                "prepared_request": prepared,
            }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 2)
        return {
            "ok": False,
            "status_code": 0,
            "reason_phrase": type(exc).__name__,
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
            "size_bytes": 0,
            "url": prepared["url"],
            "headers": {},
            "body_text": "",
            "body_json": None,
            "prepared_request": prepared,
        }
