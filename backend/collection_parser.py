"""Postman Collection v2.1.0 Parser, Normalizer, & Exporter.

Handles full ingestion of Postman Collection Format v2.1.0 schemas, including:
- Recursive folder (`item-group`) and request (`item`) traversal.
- Normalization of undocumented Postman export edge cases:
  - `request` represented as a plain URL string vs. a full Request object.
  - `url` represented as a plain string vs. a structured URL object with
    polymorphic `host` (string or list) and `path` (string or list of segments/objects).
  - `header` represented as a raw newline-delimited string vs. list of dicts.
  - Body modes: `raw`, `urlencoded`, `formdata`, `graphql`, `file`.
  - Auth blocks: `bearer`, `basic`, `apikey`, `oauth2`, `noauth`.
  - Collection-level variables and scripts (`event`: `prerequest`, `test`).
- Full round-trip export back to valid Postman Collection v2.1.0 JSON.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

POSTMAN_SCHEMA_V2_1_0 = "https://schema.postman.com/json/collection/v2.1.0/collection.json"
OPENPOST_COLLECTION_SCHEMA_V1 = "https://openpost.dev/schema/v1/collection.json"


@dataclass
class KeyValueItem:
    key: str
    value: str = ""
    description: str = ""
    disabled: bool = False
    type: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedRequest:
    id: str
    name: str
    method: str
    raw_url: str
    folder_path: list[str] = field(default_factory=list)
    headers: list[dict[str, Any]] = field(default_factory=list)
    query_params: list[dict[str, Any]] = field(default_factory=list)
    path_variables: list[dict[str, Any]] = field(default_factory=list)
    body: dict[str, Any] | None = None
    auth: dict[str, Any] | None = None
    description: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedFolder:
    id: str
    name: str
    folder_path: list[str] = field(default_factory=list)
    description: str = ""
    auth: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedCollection:
    id: str
    name: str
    description: str
    schema: str = OPENPOST_COLLECTION_SCHEMA_V1
    variables: list[dict[str, Any]] = field(default_factory=list)
    auth: dict[str, Any] | None = None
    folders: list[ParsedFolder] = field(default_factory=list)
    requests: list[ParsedRequest] = field(default_factory=list)
    raw_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "variables": self.variables,
            "auth": self.auth,
            "folders": [f.to_dict() for f in self.folders],
            "requests": [r.to_dict() for r in self.requests],
            "raw_events": self.raw_events,
        }


def _extract_description(desc: Any) -> str:
    """Normalize Postman description which can be a string, dict, or None."""
    if desc is None:
        return ""
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return str(desc.get("content", ""))
    return str(desc)


def _normalize_url(url_node: Any) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize a Postman `url` field (string or URL object).

    Returns:
        tuple of (raw_url, query_params, path_variables)
    """
    if url_node is None:
        return "", [], []

    if isinstance(url_node, str):
        raw_url = url_node
        query_params: list[dict[str, Any]] = []
        if "?" in raw_url:
            _, query_str = raw_url.split("?", 1)
            for part in query_str.split("&"):
                if not part:
                    continue
                if "=" in part:
                    k, v = part.split("=", 1)
                else:
                    k, v = part, ""
                query_params.append({"key": k, "value": v, "description": "", "disabled": False})
        return raw_url, query_params, []

    if isinstance(url_node, dict):
        raw_url = url_node.get("raw", "")

        # Extract query parameters
        query_params = []
        for q in url_node.get("query", []) or []:
            if isinstance(q, dict):
                query_params.append(
                    {
                        "key": str(q.get("key") or ""),
                        "value": "" if q.get("value") is None else str(q.get("value")),
                        "description": _extract_description(q.get("description")),
                        "disabled": bool(q.get("disabled", False)),
                    }
                )

        # Extract path variables (`variable` array in URL object)
        path_variables = []
        for v in url_node.get("variable", []) or []:
            if isinstance(v, dict):
                path_variables.append(
                    {
                        "key": str(v.get("key") or v.get("id") or ""),
                        "value": "" if v.get("value") is None else str(v.get("value")),
                        "description": _extract_description(v.get("description")),
                    }
                )

        # Edge Case: Exported v2.1.0 URLs sometimes omit `raw` and only populate protocol/host/path
        if not raw_url:
            protocol = url_node.get("protocol", "")
            host = url_node.get("host", [])
            if isinstance(host, list):
                host_str = ".".join(str(h) for h in host)
            else:
                host_str = str(host or "")

            port = url_node.get("port", "")
            path = url_node.get("path", [])
            if isinstance(path, list):
                path_segments = []
                for seg in path:
                    if isinstance(seg, dict):
                        path_segments.append(str(seg.get("value", "")))
                    else:
                        path_segments.append(str(seg))
                path_str = "/".join(path_segments)
            else:
                path_str = str(path or "").lstrip("/")

            prefix = f"{protocol}://" if protocol else ""
            port_str = f":{port}" if port else ""
            slash = "/" if (host_str and path_str and not path_str.startswith("/")) else ""
            raw_url = f"{prefix}{host_str}{port_str}{slash}{path_str}"

            active_queries = [
                f"{q['key']}={q['value']}" for q in query_params if not q.get("disabled", False) and q.get("key")
            ]
            if active_queries:
                raw_url = f"{raw_url}?{'&'.join(active_queries)}"

        return raw_url, query_params, path_variables

    return str(url_node), [], []


def _normalize_headers(header_node: Any) -> list[dict[str, Any]]:
    """Normalize Postman `header` which may be a list of dicts or a raw string."""
    if not header_node:
        return []

    if isinstance(header_node, str):
        headers = []
        for line in header_node.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            headers.append(
                {
                    "key": k.strip(),
                    "value": v.strip(),
                    "description": "",
                    "disabled": False,
                }
            )
        return headers

    if isinstance(header_node, list):
        headers = []
        for h in header_node:
            if isinstance(h, dict):
                headers.append(
                    {
                        "key": str(h.get("key", "")),
                        "value": str(h.get("value", "")),
                        "description": _extract_description(h.get("description")),
                        "disabled": bool(h.get("disabled", False) or (h.get("enabled") is False)),
                    }
                )
        return headers

    return []


def _normalize_body(body_node: Any, legacy_container: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Normalize Postman `body` object across raw, urlencoded, formdata, graphql, file modes.

    Also handles legacy v9.x / Scratch Pad models where body was stored via
    `dataMode`, `rawModeData`, or `data` directly on the item/request node.
    """
    if not body_node or not isinstance(body_node, dict):
        # Check if legacy container has dataMode / rawModeData / data
        if legacy_container and isinstance(legacy_container, dict):
            legacy_mode = str(legacy_container.get("dataMode", "")).lower()
            if legacy_mode == "raw":
                raw_val = str(legacy_container.get("rawModeData") or legacy_container.get("data") or "")
                return {"mode": "raw", "raw": raw_val, "disabled": False, "language": "json"}
            elif legacy_mode in ("urlencoded", "params"):
                items = []
                for entry in legacy_container.get("data", []) or []:
                    if isinstance(entry, dict):
                        items.append(
                            {
                                "key": str(entry.get("key", "")),
                                "value": str(entry.get("value", "")),
                                "type": str(entry.get("type", "text")),
                                "description": _extract_description(entry.get("description")),
                                "disabled": bool(entry.get("disabled", False) or not entry.get("enabled", True)),
                            }
                        )
                target_mode = "urlencoded" if legacy_mode == "urlencoded" else "formdata"
                return {"mode": target_mode, target_mode: items, "disabled": False, "language": "text"}
        return None

    mode = body_node.get("mode", "raw")
    options = body_node.get("options", {})
    language = (
        options.get("raw", {}).get("language", "json")
        if isinstance(options, dict)
        else "text"
    )

    normalized: dict[str, Any] = {
        "mode": mode,
        "disabled": bool(body_node.get("disabled", False)),
        "language": language,
    }

    if mode == "raw":
        normalized["raw"] = body_node.get("raw", "")
    elif mode in ("urlencoded", "formdata"):
        items = []
        for entry in body_node.get(mode, []) or []:
            if isinstance(entry, dict):
                items.append(
                    {
                        "key": str(entry.get("key", "")),
                        "value": str(entry.get("value", entry.get("src", ""))),
                        "type": str(entry.get("type", "text")),
                        "description": _extract_description(entry.get("description")),
                        "disabled": bool(entry.get("disabled", False)),
                    }
                )
        normalized[mode] = items
    elif mode == "graphql":
        normalized["graphql"] = body_node.get("graphql", {"query": "", "variables": ""})
    elif mode == "file":
        normalized["file"] = body_node.get("file", {})
    else:
        normalized["raw"] = body_node.get("raw", "")

    return normalized


def _normalize_auth(auth_node: Any) -> dict[str, Any] | None:
    """Normalize Postman `auth` blocks (`bearer`, `basic`, `apikey`, `noauth`, etc.).

    Postman v2.1.0 stores auth parameters as an array of `{key, value, type}` dicts
    under the auth type key, whereas older exports or internal IPC payloads sometimes
    store them as a flat key-value object. This function normalizes both into a clean
    dictionary alongside the original type.
    """
    if not auth_node or not isinstance(auth_node, dict):
        return None

    auth_type = str(auth_node.get("type", "noauth")).lower()
    if auth_type == "noauth":
        return {"type": "noauth", "params": {}}

    raw_params = auth_node.get(auth_type, [])
    params: dict[str, Any] = {}
    if isinstance(raw_params, list):
        for entry in raw_params:
            if isinstance(entry, dict) and "key" in entry:
                params[str(entry["key"])] = entry.get("value", "")
    elif isinstance(raw_params, dict):
        params = dict(raw_params)

    return {"type": auth_type, "params": params}


def _parse_items_recursive(
    items: list[Any],
    folder_path: list[str],
    folders_out: list[ParsedFolder],
    requests_out: list[ParsedRequest],
    inherited_auth: dict[str, Any] | None = None,
) -> None:
    """Recursively traverse `item` arrays to extract folders and requests."""
    for item in items:
        if not isinstance(item, dict):
            continue

        item_raw_id = str(item.get("id") or item.get("_postman_id") or item.get("uid") or uuid.uuid4())
        # Clean compound UIDs (e.g., '123456-abcdef-guid' -> 'abcdef-guid')
        item_id = item_raw_id.split("-", 1)[1] if ("-" in item_raw_id and len(item_raw_id.split("-")) > 4 and item_raw_id.split("-")[0].isdigit()) else item_raw_id
        item_name = str(item.get("name") or "Untitled")
        item_desc = _extract_description(item.get("description"))
        item_auth = _normalize_auth(item.get("auth")) or inherited_auth

        # In Postman v2.1.0, an `item-group` (folder) has a nested `item` list and no `request` key
        if "item" in item and isinstance(item["item"], list) and "request" not in item:
            folder = ParsedFolder(
                id=item_id,
                name=item_name,
                folder_path=list(folder_path),
                description=item_desc,
                auth=item_auth,
            )
            folders_out.append(folder)
            _parse_items_recursive(
                item["item"],
                folder_path + [item_name],
                folders_out,
                requests_out,
                inherited_auth=item_auth,
            )
            continue

        # Otherwise it's a request `item`
        req_node = item.get("request")
        if req_node is None and ("dataMode" in item or "rawModeData" in item or "url" in item):
            req_node = item

        if req_node is None:
            continue

        # Edge Case: `request` can be a plain URL string (valid in v2.1.0 draft-07)
        if isinstance(req_node, str):
            raw_url, query_params, path_vars = _normalize_url(req_node)
            parsed_req = ParsedRequest(
                id=item_id,
                name=item_name,
                method="GET",
                raw_url=raw_url,
                folder_path=list(folder_path),
                headers=[],
                query_params=query_params,
                path_variables=path_vars,
                body=None,
                auth=item_auth,
                description=item_desc,
                events=item.get("event", []) or [],
            )
            requests_out.append(parsed_req)
            continue

        if isinstance(req_node, dict):
            method = str(req_node.get("method") or "GET").upper()
            raw_url, query_params, path_vars = _normalize_url(req_node.get("url"))
            # Support both standard header and legacy headerData
            headers = _normalize_headers(req_node.get("header") or req_node.get("headerData") or item.get("headerData"))
            body = _normalize_body(req_node.get("body"), legacy_container=req_node) or _normalize_body(None, legacy_container=item)
            req_auth = _normalize_auth(req_node.get("auth")) or item_auth
            req_desc = _extract_description(req_node.get("description")) or item_desc

            parsed_req = ParsedRequest(
                id=item_id,
                name=item_name,
                method=method,
                raw_url=raw_url,
                folder_path=list(folder_path),
                headers=headers,
                query_params=query_params,
                path_variables=path_vars,
                body=body,
                auth=req_auth,
                description=req_desc,
                events=item.get("event", []) or [],
            )
            requests_out.append(parsed_req)


def parse_openpost_collection_dict(data: dict[str, Any]) -> ParsedCollection:
    """Parse an OpenPost native clean-room plain-text collection format dictionary."""
    if not isinstance(data, dict):
        raise ValueError("Collection payload must be a JSON object.")

    col_id = str(data.get("id") or uuid.uuid4())
    name = str(data.get("name") or "Untitled Collection")
    description = str(data.get("description") or "")
    schema = str(data.get("schema") or OPENPOST_COLLECTION_SCHEMA_V1)

    folders: list[ParsedFolder] = []
    for f in data.get("folders") or []:
        if isinstance(f, dict):
            folders.append(
                ParsedFolder(
                    id=str(f.get("id") or uuid.uuid4()),
                    name=str(f.get("name") or "Folder"),
                    folder_path=list(f.get("folder_path") or []),
                    description=str(f.get("description") or ""),
                    auth=f.get("auth"),
                )
            )

    requests: list[ParsedRequest] = []
    for r in data.get("requests") or []:
        if isinstance(r, dict):
            requests.append(
                ParsedRequest(
                    id=str(r.get("id") or uuid.uuid4()),
                    name=str(r.get("name") or "Untitled Request"),
                    method=str(r.get("method") or "GET").upper(),
                    raw_url=str(r.get("raw_url") or ""),
                    folder_path=list(r.get("folder_path") or []),
                    headers=list(r.get("headers") or []),
                    query_params=list(r.get("query_params") or []),
                    path_variables=list(r.get("path_variables") or []),
                    body=r.get("body"),
                    auth=r.get("auth"),
                    description=str(r.get("description") or ""),
                    events=list(r.get("events") or []),
                )
            )

    return ParsedCollection(
        id=col_id,
        name=name,
        description=description,
        schema=schema,
        variables=list(data.get("variables") or []),
        auth=data.get("auth"),
        folders=folders,
        requests=requests,
        raw_events=list(data.get("raw_events") or []),
    )


def parse_postman_collection_dict(data: dict[str, Any]) -> ParsedCollection:
    """Parse a Postman Collection v2.1.0 or OpenPost native dictionary into a normalized ParsedCollection."""
    if not isinstance(data, dict):
        raise ValueError("Collection payload must be a JSON object.")

    # Check for OpenPost native format
    if data.get("schema") == OPENPOST_COLLECTION_SCHEMA_V1 or (
        "info" not in data and ("folders" in data or "requests" in data or "variables" in data)
    ):
        return parse_openpost_collection_dict(data)

    # Unwrap if wrapped inside `{"collection": {...}}` (common in Postman Cloud API / IPC payloads)
    if "collection" in data and isinstance(data["collection"], dict) and "info" in data["collection"]:
        data = data["collection"]

    info = data.get("info")
    if not isinstance(info, dict):
        raise ValueError("Invalid Postman Collection: missing `info` object.")

    col_id = str(info.get("_postman_id") or info.get("id") or uuid.uuid4())
    name = str(info.get("name") or "Untitled Collection")
    description = _extract_description(info.get("description"))
    schema = str(info.get("schema") or POSTMAN_SCHEMA_V2_1_0)

    variables: list[dict[str, Any]] = []
    for var in data.get("variable", []) or []:
        if isinstance(var, dict):
            variables.append(
                {
                    "key": str(var.get("key") or var.get("id") or ""),
                    "value": "" if var.get("value") is None else str(var.get("value")),
                    "type": str(var.get("type") or "string"),
                    "disabled": bool(var.get("disabled", False)),
                }
            )

    collection_auth = _normalize_auth(data.get("auth"))
    folders: list[ParsedFolder] = []
    requests: list[ParsedRequest] = []

    items = data.get("item", [])
    if isinstance(items, list):
        _parse_items_recursive(
            items,
            folder_path=[],
            folders_out=folders,
            requests_out=requests,
            inherited_auth=collection_auth,
        )

    return ParsedCollection(
        id=col_id,
        name=name,
        description=description,
        schema=schema,
        variables=variables,
        auth=collection_auth,
        folders=folders,
        requests=requests,
        raw_events=data.get("event", []) or [],
    )


def parse_postman_collection_file(file_path: str | Path) -> ParsedCollection:
    """Load and parse a Postman Collection v2.1.0 JSON file from disk."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Collection file not found: {path}")

    with path.open("r", encoding="utf-8-sig") as f:
        raw_data = json.load(f)

    return parse_postman_collection_dict(raw_data)


def export_to_postman_v21(collection: dict[str, Any] | ParsedCollection) -> dict[str, Any]:
    """Export an OpenPost collection dict or ParsedCollection back to strict Postman v2.1.0 format."""
    col_dict = collection.to_dict() if isinstance(collection, ParsedCollection) else collection

    def _build_auth_v21(auth_obj: dict[str, Any] | None) -> dict[str, Any] | None:
        if not auth_obj or not isinstance(auth_obj, dict):
            return None
        auth_type = auth_obj.get("type", "noauth")
        if auth_type == "noauth":
            return {"type": "noauth"}
        params = auth_obj.get("params", {})
        param_list = [
            {"key": k, "value": v, "type": "string"}
            for k, v in params.items()
        ]
        return {"type": auth_type, auth_type: param_list}

    def _build_request_item_v21(req: dict[str, Any]) -> dict[str, Any]:
        raw_url = req.get("raw_url", "")
        query_params = req.get("query_params", [])
        url_obj: dict[str, Any] = {"raw": raw_url}
        if query_params:
            url_obj["query"] = [
                {
                    "key": q.get("key", ""),
                    "value": q.get("value", ""),
                    "description": q.get("description", ""),
                    "disabled": bool(q.get("disabled", False)),
                }
                for q in query_params
            ]
        if req.get("path_variables"):
            url_obj["variable"] = req["path_variables"]

        req_payload: dict[str, Any] = {
            "method": req.get("method", "GET"),
            "header": req.get("headers", []),
            "url": url_obj,
        }
        if req.get("body"):
            body_in = req["body"]
            mode = body_in.get("mode", "raw")
            body_out: dict[str, Any] = {"mode": mode}
            if mode == "raw":
                body_out["raw"] = body_in.get("raw", "")
                body_out["options"] = {"raw": {"language": body_in.get("language", "json")}}
            elif mode in ("urlencoded", "formdata"):
                body_out[mode] = body_in.get(mode, [])
            elif mode == "graphql":
                body_out["graphql"] = body_in.get("graphql", {})
            req_payload["body"] = body_out

        if req.get("auth"):
            req_payload["auth"] = _build_auth_v21(req["auth"])
        if req.get("description"):
            req_payload["description"] = req["description"]

        item_out: dict[str, Any] = {
            "id": req.get("id", str(uuid.uuid4())),
            "name": req.get("name", "Untitled Request"),
            "request": req_payload,
            "response": [],
        }
        if req.get("events"):
            item_out["event"] = req["events"]
        return item_out

    # Reconstruct folder hierarchy
    root_items: list[dict[str, Any]] = []
    folder_map: dict[tuple[str, ...], dict[str, Any]] = {}

    def _ensure_folder(path_tuple: tuple[str, ...]) -> list[dict[str, Any]]:
        if not path_tuple:
            return root_items
        if path_tuple in folder_map:
            return folder_map[path_tuple]["item"]
        parent_items = _ensure_folder(path_tuple[:-1])
        folder_node: dict[str, Any] = {
            "name": path_tuple[-1],
            "item": [],
        }
        parent_items.append(folder_node)
        folder_map[path_tuple] = folder_node
        return folder_node["item"]

    # Ensure explicitly defined empty folders are also created
    for folder in col_dict.get("folders", []):
        f_path = tuple(folder.get("folder_path", []) + [folder.get("name", "Folder")])
        _ensure_folder(f_path)
        if f_path in folder_map:
            if folder.get("description"):
                folder_map[f_path]["description"] = folder["description"]
            if folder.get("auth"):
                folder_map[f_path]["auth"] = _build_auth_v21(folder["auth"])

    for req in col_dict.get("requests", []):
        f_path = tuple(req.get("folder_path", []))
        target_list = _ensure_folder(f_path)
        target_list.append(_build_request_item_v21(req))

    exported: dict[str, Any] = {
        "info": {
            "_postman_id": col_dict.get("id", str(uuid.uuid4())),
            "name": col_dict.get("name", "Exported Collection"),
            "description": col_dict.get("description", ""),
            "schema": POSTMAN_SCHEMA_V2_1_0,
        },
        "item": root_items,
        "variable": col_dict.get("variables", []),
    }
    if col_dict.get("auth"):
        exported["auth"] = _build_auth_v21(col_dict["auth"])
    if col_dict.get("raw_events"):
        exported["event"] = col_dict["raw_events"]

    return exported


def export_to_openpost_native(collection: dict[str, Any] | ParsedCollection) -> dict[str, Any]:
    """Serialize collection into OpenPost's clean-room native plain-text JSON schema."""
    if isinstance(collection, ParsedCollection):
        col_dict = collection.to_dict()
    else:
        col_dict = dict(collection)
    col_dict["schema"] = OPENPOST_COLLECTION_SCHEMA_V1
    return col_dict


parse_collection_file = parse_postman_collection_file
