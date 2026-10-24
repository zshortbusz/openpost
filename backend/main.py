"""OpenPost FastAPI Server — Local-First REST API & Static WebUI Host.

Provides full HTTP REST parity with `backend/mcp_server.py` and serves
the dark-mode frontend at `/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import mcp_server

app = FastAPI(
    title="OpenPost Local API & Agentic Engine",
    version="0.1.0",
    description="Clean-room local-first Postman Scratch Pad replacement with full MCP parity.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class ImportCollectionPayload(BaseModel):
    file_path: str | None = None
    collection_json: dict[str, Any] | str | None = None


class CreateCollectionPayload(BaseModel):
    name: str
    description: str = ""
    variables: list[dict[str, Any]] = Field(default_factory=list)


class CreateFolderPayload(BaseModel):
    name: str
    parent_folder_path: list[str] = Field(default_factory=list)
    description: str = ""


class SaveRequestPayload(BaseModel):
    request_id: str | None = None
    name: str
    method: str = "GET"
    raw_url: str
    folder_path: list[str] = Field(default_factory=list)
    headers: list[dict[str, Any]] = Field(default_factory=list)
    query_params: list[dict[str, Any]] = Field(default_factory=list)
    body: dict[str, Any] | None = None
    auth: dict[str, Any] | None = None
    description: str = ""
    events: list[dict[str, Any]] | None = None
    path_variables: list[dict[str, Any]] | None = None


class SendRequestPayload(BaseModel):
    method: str = "GET"
    raw_url: str
    headers: list[dict[str, Any]] | dict[str, str] = Field(default_factory=list)
    query_params: list[dict[str, Any]] | dict[str, str] = Field(default_factory=list)
    body: dict[str, Any] | str | None = None
    auth: dict[str, Any] | None = None
    collection_id: str | None = None
    request_id: str | None = None
    environment_id: str | None = None
    override_variables: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0


class SaveEnvironmentPayload(BaseModel):
    environment_id: str | None = None
    name: str
    variables: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)


class RunCollectionPayload(BaseModel):
    folder_filter: list[str] | None = None
    environment_id: str | None = None
    override_variables: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "openpost",
        "version": "0.1.0",
        "mcp_tools_available": 22,
    }


@app.get("/api/collections")
def api_list_collections() -> list[dict[str, Any]]:
    return mcp_server.list_collections()


@app.post("/api/collections")
def api_create_collection(payload: CreateCollectionPayload) -> dict[str, Any]:
    return mcp_server.create_collection(
        name=payload.name,
        description=payload.description,
        variables=payload.variables,
    )


@app.post("/api/collections/import")
def api_import_collection(payload: ImportCollectionPayload) -> dict[str, Any]:
    try:
        return mcp_server.import_postman_collection(
            file_path=payload.file_path,
            collection_json=payload.collection_json,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/collections/{collection_id}")
def api_get_collection(collection_id: str) -> dict[str, Any]:
    try:
        return mcp_server.get_collection(collection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/collections/{collection_id}/export")
def api_export_collection(collection_id: str) -> dict[str, Any]:
    try:
        return mcp_server.export_postman_collection(collection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/collections/{collection_id}")
def api_delete_collection(collection_id: str) -> dict[str, Any]:
    return mcp_server.delete_collection(collection_id)


@app.post("/api/collections/{collection_id}/folders")
def api_create_folder(collection_id: str, payload: CreateFolderPayload) -> dict[str, Any]:
    try:
        return mcp_server.create_folder(
            collection_id=collection_id,
            name=payload.name,
            parent_folder_path=payload.parent_folder_path,
            description=payload.description,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/collections/{collection_id}/requests")
def api_save_request(collection_id: str, payload: SaveRequestPayload) -> dict[str, Any]:
    try:
        return mcp_server.save_request(
            collection_id=collection_id,
            request_id=payload.request_id,
            name=payload.name,
            method=payload.method,
            raw_url=payload.raw_url,
            folder_path=payload.folder_path,
            headers=payload.headers,
            query_params=payload.query_params,
            body=payload.body,
            auth=payload.auth,
            description=payload.description,
            events=payload.events,
            path_variables=payload.path_variables,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/collections/{collection_id}/requests/{request_id}")
def api_delete_request(collection_id: str, request_id: str) -> dict[str, Any]:
    return mcp_server.delete_request(collection_id=collection_id, request_id=request_id)


@app.post("/api/collections/{collection_id}/run")
async def api_run_collection(collection_id: str, payload: RunCollectionPayload) -> dict[str, Any]:
    try:
        return await mcp_server.run_collection(
            collection_id=collection_id,
            folder_filter=payload.folder_filter,
            environment_id=payload.environment_id,
            override_variables=payload.override_variables,
            timeout_seconds=payload.timeout_seconds,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/requests/interpolate")
def api_interpolate_preview(payload: SendRequestPayload) -> dict[str, Any]:
    return mcp_server.interpolate_preview(
        raw_url=payload.raw_url,
        method=payload.method,
        headers=payload.headers,
        query_params=payload.query_params,
        body=payload.body,
        auth=payload.auth,
        collection_id=payload.collection_id,
        environment_id=payload.environment_id,
        override_variables=payload.override_variables,
    )


@app.post("/api/requests/send")
async def api_send_request(payload: SendRequestPayload) -> dict[str, Any]:
    if payload.collection_id and payload.request_id:
        return await mcp_server.run_collection_request(
            collection_id=payload.collection_id,
            request_id=payload.request_id,
            environment_id=payload.environment_id,
            override_variables=payload.override_variables,
            timeout_seconds=payload.timeout_seconds,
        )
    return await mcp_server.send_request(
        method=payload.method,
        raw_url=payload.raw_url,
        headers=payload.headers,
        query_params=payload.query_params,
        body=payload.body,
        auth=payload.auth,
        environment_id=payload.environment_id,
        override_variables=payload.override_variables,
        timeout_seconds=payload.timeout_seconds,
    )


@app.get("/api/environments")
def api_list_environments() -> list[dict[str, Any]]:
    return mcp_server.list_environments()


@app.post("/api/environments")
def api_save_environment(payload: SaveEnvironmentPayload) -> dict[str, Any]:
    return mcp_server.save_environment(
        name=payload.name,
        variables=payload.variables,
        environment_id=payload.environment_id,
    )


@app.delete("/api/environments/{environment_id}")
def api_delete_environment(environment_id: str) -> dict[str, Any]:
    return mcp_server.delete_environment(environment_id)


@app.get("/api/history")
def api_list_history(limit: int = 50) -> list[dict[str, Any]]:
    return mcp_server.list_request_history(limit=limit)


@app.get("/api/history/{history_id}")
def api_get_history_entry(history_id: str) -> dict[str, Any]:
    try:
        return mcp_server.get_history_entry(history_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/history")
def api_clear_history() -> dict[str, Any]:
    return mcp_server.clear_request_history()




# ---------------------------------------------------------------------------
# Static Frontend Serving
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/styles.css")
def serve_styles() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")


@app.get("/app.js")
def serve_app_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")
