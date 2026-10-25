# AGENTS.md — Agentic Operation Manual for OpenPost

Welcome, AI Agent! This document is your comprehensive operational guide for interacting with, running, testing, and modifying **OpenPost**.

---

## 1. Project Mission & Clean-Room Architecture

**OpenPost** is a lightning-fast, local-first, offline-capable API testing client engineered as a **strict clean-room** alternative to Postman's legacy Scratch Pad. It requires zero cloud accounts, sends zero telemetry, and exposes **100% of its functionality through a Model Context Protocol (MCP) server** so AI agents can operate it autonomously.

### Clean-Room Invariants & Legal Guarantees:
1. **Zero Decompiled Code or Lifted Strings**: The codebase is written strictly from scratch. Never introduce raw strings, internal IPC channel names, event bus topics, or decompiled assets from Postman's unpacked Electron bundle (`app.asar`).
2. **Native Plain-Text Storage**: Local collections are persisted as plain-text JSON files in `data/collections/<id>.json` declaring OpenPost's native schema (`https://openpost.dev/schema/v1/collection.json`). Never mirror internal LevelDB/IndexedDB database structures.
3. **Public Interchange Standards**: Interoperability is restricted to the publicly published Postman Collection Format v2.1.0 open schema (Apache-2.0).
4. **Git-Native Simplicity**: Plain-text collection files allow line-by-line diffing, pull requests, and standard merge conflict resolution without database locking.

### Core Architectural Layers:
```
OpenPost Workspace
├── backend/            # Python 3.10+ FastAPI core + 22-tool FastMCP server
│   ├── collection_parser.py # Postman v2.1.0 & native schema parser/exporter
│   ├── request_engine.py    # HTTP client (httpx), {{var}} & :path interpolation
│   ├── local_db.py          # SQLite (history/environments) + Flat JSON (collections)
│   ├── script_runner.py     # Python bridge to sandboxed JavaScript runtime
│   ├── script_sandbox.js    # Node.js runner implementing pm.* and Chai assertions
│   ├── main.py              # FastAPI REST endpoints + WebUI static host
│   └── mcp_server.py        # 22-tool Model Context Protocol (MCP) server
├── frontend/           # Vanilla JS/CSS dark-mode Scratch Pad WebUI
├── src-tauri/          # Tauri v2 desktop application & installer builds (Rust)
├── desktop/            # Instant native desktop launcher (Edge/Chromium app mode)
└── tests/              # Pytest suite covering parser, engine, MCP, and desktop
```

---

## 2. Agent Quickstart & Terminal Commands

When working in this repository, use these commands:

### Running Tests
```bash
# Run the complete test suite (30 unit, integration, security, and packaging tests):
pytest -v

# Or within the virtual environment:
.\.venv\Scripts\pytest -v
```

### Launching OpenPost Server & WebUI
```bash
# Launch FastAPI backend & WebUI at http://127.0.0.1:8000:
uvicorn backend.main:app --port 8000 --reload
```

### Launching Native Desktop App Window
```bash
# Instant zero-build desktop window (Edge/Chromium app mode):
python desktop/run_desktop.py

# Verify desktop launcher in headless/dry-run mode:
python desktop/run_desktop.py --check
```

### Running Sample Collections Live
```bash
# Run production Postman Echo & GitHub API test suites live:
python scripts/run_sample_collections.py
```

---

## 3. Complete MCP Tool Catalog (22 Tools)

When connected to `backend/mcp_server.py` via stdio or streamable HTTP, call these tools directly:

### Collection Management
1. `import_postman_collection(file_path?, collection_json?)`: Ingest Postman Collection v2.1.0 or legacy Scratch Pad JSON.
2. `export_postman_collection(collection_id, output_path?)`: Export collection back to strict Postman v2.1.0 JSON format.
3. `list_collections()`: Return metadata for all collections stored in `data/collections/`.
4. `get_collection(collection_id)`: Retrieve full collection tree (folders, requests, variables).
5. `create_collection(name, description?, variables?)`: Create a new collection.
6. `delete_collection(collection_id)`: Remove a collection and its JSON file.

### Request & Folder Authoring
7. `create_folder(collection_id, name, parent_folder_path?, description?)`: Add a folder (`item-group`).
8. `save_request(collection_id, name, method, raw_url, request_id?, folder_path?, headers?, query_params?, body?, auth?, description?)`: Save/update a request.
9. `delete_request(collection_id, request_id)`: Delete a saved request.

### Request Execution & Collection Runner
10. `interpolate_preview(raw_url, method?, headers?, query_params?, body?, auth?, collection_id?, environment_id?, override_variables?)`: Dry-run resolution of variables.
11. `send_request(method, raw_url, headers?, query_params?, body?, auth?, environment_id?, override_variables?, timeout_seconds?)`: Execute ad-hoc HTTP request.
12. `run_collection_request(collection_id, request_id, environment_id?, override_variables?, timeout_seconds?)`: Execute a specific saved request with pre-request/test script execution.
13. `run_collection(collection_id, folder_filter?, environment_id?, override_variables?, timeout_seconds?)`: **Collection Runner**: execute all requests sequentially, running `pm.*` scripts and reporting assertion outcomes.
14. `execute_postman_script(script, listen?, request_data?, response_data?, environment_id?, override_variables?)`: Execute sandboxed JavaScript with `pm.test` assertions.

### Environments & Variables
15. `list_environments()`: Query all environments from SQLite.
16. `get_environment(environment_id)`: Get environment variables.
17. `save_environment(name, variables, environment_id?)`: Create/upsert environment.
18. `set_environment_variable(environment_id, key, value?, enabled?)`: Set or delete a single environment variable.
19. `delete_environment(environment_id)`: Delete an environment.

### History & Auditing
20. `list_request_history(limit?)`: Query past HTTP executions from SQLite.
21. `get_history_entry(history_id)`: Retrieve complete request and response payloads.
22. `clear_request_history()`: Clear request execution history.

---

## 4. Postman Script Sandbox (`pm.*`) Capabilities

The script engine runs inside Node.js (`backend/script_sandbox.js`) and supports:
- `pm.environment.get / set / unset`
- `pm.collectionVariables.get / set / unset`
- `pm.variables.get / set`
- `pm.response.code`, `pm.response.status`, `pm.response.headers.get("name")`
- `pm.response.text()`, `pm.response.json()`
- `pm.response.to.have.status(code)`
- `pm.response.to.be.success / clientError / serverError`
- `pm.test("name", function () { ... })`
- `pm.expect(actual).to.equal(expected) / to.eql(expected) / to.include() / to.be.true / to.be.false / to.be.null / to.be.undefined / to.be.ok`

---

## 5. Development Invariants

1. **Local-First & Zero-Telemetry**: Never add outbound network calls to cloud telemetry or analytics services.
2. **Clean-Room Native Persistence**: Local collections are stored using OpenPost's native schema (`https://openpost.dev/schema/v1/collection.json`) in human-readable plain-text JSON.
3. **Postman v2.1.0 Interoperability**: Any collection exported by OpenPost via `export_postman_collection` MUST validate against `https://schema.postman.com/json/collection/v2.1.0/collection.json`.
4. **Preserve Comments**: Maintain documentation integrity across all existing Python and JavaScript files.
5. **All Tests Must Pass**: Run `pytest -v` before submitting any modification.
