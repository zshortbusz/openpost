"""Local Persistence Layer — SQLite (History & Environments) + Flat JSON (Collections).

Provides zero-cloud, local-first storage for OpenPost:
- Collections are stored as human-readable JSON files in `data/collections/<id>.json`.
- Environments and Request History are persisted in `data/openpost.db` (SQLite).
"""

from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterator

from backend.collection_parser import (
    OPENPOST_COLLECTION_SCHEMA_V1,
    POSTMAN_SCHEMA_V2_1_0,
    ParsedCollection,
    export_to_postman_v21,
    parse_postman_collection_dict,
)


class LocalStore:
    """Manages local SQLite database and flat JSON collection files."""

    def __init__(self, base_data_dir: str | Path | None = None) -> None:
        if base_data_dir is None:
            base_data_dir = Path(__file__).resolve().parent.parent / "data"
        self.base_dir = Path(base_data_dir)
        self.collections_dir = self.base_dir / "collections"
        self.db_path = self.base_dir / "openpost.db"

        self.collections_dir.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    variables_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS request_history (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    collection_id TEXT,
                    request_id TEXT,
                    method TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    elapsed_ms REAL NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Collections (Flat JSON files in data/collections/)
    # ------------------------------------------------------------------

    def _collection_path(self, collection_id: str) -> Path:
        safe_id = "".join(c for c in str(collection_id) if c.isalnum() or c in ("-", "_"))
        if not safe_id:
            raise ValueError(f"Invalid collection_id: {collection_id!r}")
        return self.collections_dir / f"{safe_id}.json"

    def save_collection(self, collection: ParsedCollection | dict[str, Any]) -> dict[str, Any]:
        col_dict = collection.to_dict() if isinstance(collection, ParsedCollection) else dict(collection)
        raw_id = str(col_dict.get("id") or "")
        safe_id = "".join(c for c in raw_id if c.isalnum() or c in ("-", "_"))
        if not safe_id:
            safe_id = str(uuid.uuid4())
        col_dict["id"] = safe_id
        col_dict["schema"] = OPENPOST_COLLECTION_SCHEMA_V1
        col_dict.setdefault("name", "Untitled Collection")
        col_dict.setdefault("description", "")
        col_dict.setdefault("variables", [])
        col_dict.setdefault("folders", [])
        col_dict.setdefault("requests", [])
        path = self._collection_path(col_dict["id"])
        with path.open("w", encoding="utf-8") as f:
            json.dump(col_dict, f, indent=2)
        return col_dict

    def create_collection(
        self,
        name: str,
        description: str = "",
        variables: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        col = ParsedCollection(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            schema=OPENPOST_COLLECTION_SCHEMA_V1,
            variables=variables or [],
            folders=[],
            requests=[],
        )
        return self.save_collection(col)

    def import_postman_json(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_postman_collection_dict(raw_payload)
        parsed.schema = OPENPOST_COLLECTION_SCHEMA_V1
        return self.save_collection(parsed)

    def list_collections(self) -> list[dict[str, Any]]:
        summaries = []
        for file_path in sorted(self.collections_dir.glob("*.json")):
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                summaries.append(
                    {
                        "id": data.get("id", file_path.stem),
                        "name": data.get("name", "Untitled"),
                        "description": data.get("description", ""),
                        "request_count": len(data.get("requests", [])),
                        "folder_count": len(data.get("folders", [])),
                        "variable_count": len(data.get("variables", [])),
                    }
                )
            except Exception:
                continue
        return summaries

    def get_collection(self, collection_id: str) -> dict[str, Any] | None:
        path = self._collection_path(collection_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def delete_collection(self, collection_id: str) -> bool:
        path = self._collection_path(collection_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def export_collection_v21(self, collection_id: str) -> dict[str, Any] | None:
        col = self.get_collection(collection_id)
        if not col:
            return None
        return export_to_postman_v21(col)

    def export_collection_native(self, collection_id: str) -> dict[str, Any] | None:
        col = self.get_collection(collection_id)
        if not col:
            return None
        col["schema"] = OPENPOST_COLLECTION_SCHEMA_V1
        return col

    def add_folder(
        self,
        collection_id: str,
        name: str,
        parent_folder_path: list[str] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        col = self.get_collection(collection_id)
        if not col:
            raise KeyError(f"Collection not found: {collection_id}")
        folder_obj = {
            "id": str(uuid.uuid4()),
            "name": name,
            "folder_path": list(parent_folder_path or []),
            "description": description,
            "auth": None,
        }
        col.setdefault("folders", []).append(folder_obj)
        self.save_collection(col)
        return folder_obj

    def upsert_request(
        self,
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
        col = self.get_collection(collection_id)
        if not col:
            raise KeyError(f"Collection not found: {collection_id}")

        reqs = col.setdefault("requests", [])
        target_id = request_id or str(uuid.uuid4())

        existing_req: dict[str, Any] | None = None
        for r in reqs:
            if r.get("id") == target_id:
                existing_req = r
                break

        final_events = events if events is not None else (existing_req.get("events", []) if existing_req else [])
        final_path_vars = path_variables if path_variables is not None else (existing_req.get("path_variables", []) if existing_req else [])

        req_payload = {
            "id": target_id,
            "name": name,
            "method": method.upper(),
            "raw_url": raw_url,
            "folder_path": list(folder_path or []),
            "headers": headers or [],
            "query_params": query_params or [],
            "path_variables": final_path_vars,
            "body": body,
            "auth": auth,
            "description": description,
            "events": final_events,
        }

        for idx, existing in enumerate(reqs):
            if existing.get("id") == target_id:
                reqs[idx] = req_payload
                self.save_collection(col)
                return req_payload

        reqs.append(req_payload)
        self.save_collection(col)
        return req_payload

    def delete_request(self, collection_id: str, request_id: str) -> bool:
        col = self.get_collection(collection_id)
        if not col:
            return False
        before = len(col.get("requests", []))
        col["requests"] = [r for r in col.get("requests", []) if r.get("id") != request_id]
        if len(col["requests"]) < before:
            self.save_collection(col)
            return True
        return False

    # ------------------------------------------------------------------
    # Environments (SQLite)
    # ------------------------------------------------------------------

    def save_environment(
        self,
        name: str,
        variables: list[dict[str, Any]] | dict[str, Any],
        env_id: str | None = None,
    ) -> dict[str, Any]:
        target_id = env_id or str(uuid.uuid4())
        if isinstance(variables, dict):
            var_list = [
                {"key": str(k), "value": str(v), "enabled": True}
                for k, v in variables.items()
            ]
        else:
            var_list = list(variables)

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO environments (id, name, variables_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    variables_json = excluded.variables_json,
                    updated_at = excluded.updated_at
                """,
                (target_id, name, json.dumps(var_list), now),
            )
            conn.commit()
        return {"id": target_id, "name": name, "variables": var_list, "updated_at": now}

    def list_environments(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, variables_json, updated_at FROM environments ORDER BY name ASC"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "variables": json.loads(r["variables_json"]),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def get_environment(self, env_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, variables_json, updated_at FROM environments WHERE id = ?",
                (env_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "variables": json.loads(row["variables_json"]),
            "updated_at": row["updated_at"],
        }

    def set_environment_variable(
        self,
        env_id: str,
        key: str,
        value: str | None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        env = self.get_environment(env_id)
        if not env:
            raise KeyError(f"Environment not found: {env_id}")
        var_list: list[dict[str, Any]] = env["variables"]
        if value is None:
            var_list = [v for v in var_list if v.get("key") != key]
        else:
            updated = False
            for v in var_list:
                if v.get("key") == key:
                    v["value"] = value
                    v["enabled"] = enabled
                    updated = True
                    break
            if not updated:
                var_list.append({"key": key, "value": value, "enabled": enabled})
        return self.save_environment(name=env["name"], variables=var_list, env_id=env_id)

    def delete_environment(self, env_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM environments WHERE id = ?", (env_id,))
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Request History (SQLite)
    # ------------------------------------------------------------------

    def record_history(
        self,
        method: str,
        url: str,
        status_code: int,
        elapsed_ms: float,
        size_bytes: int,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
        collection_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        entry_id = str(uuid.uuid4())
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO request_history (
                    id, timestamp, collection_id, request_id, method, url,
                    status_code, elapsed_ms, size_bytes, request_json, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    now,
                    collection_id,
                    request_id,
                    method.upper(),
                    url,
                    status_code,
                    elapsed_ms,
                    size_bytes,
                    json.dumps(request_data),
                    json.dumps(response_data),
                ),
            )
            conn.commit()
        return {
            "id": entry_id,
            "timestamp": now,
            "collection_id": collection_id,
            "request_id": request_id,
            "method": method.upper(),
            "url": url,
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
            "size_bytes": size_bytes,
        }

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, collection_id, request_id, method, url,
                       status_code, elapsed_ms, size_bytes
                FROM request_history
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_history_entry(self, entry_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM request_history WHERE id = ?",
                (entry_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["request"] = json.loads(data.pop("request_json"))
        data["response"] = json.loads(data.pop("response_json"))
        return data

    def clear_history(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM request_history")
            conn.commit()
            return cur.rowcount
