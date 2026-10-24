# PROJECT CONTEXT: OpenPost (Local-First Postman Alternative)
**Objective:** Build a lightning-fast, purely local, offline-first API testing client that imports Postman Collections flawlessly and exposes 100% of its capabilities via an MCP server for full agentic operation.
**Strategy:** Open-source clean-room implementation with decoupled native plain-text collection format (`https://openpost.dev/schema/v1/collection.json`) and Postman Collection Format v2.1.0 interchange compatibility.

## 1. TECH STACK (Target Architecture)
- **Backend/IPC Layer:** Python 3.10+ with FastAPI and FastMCP (`mcp`).
- **Frontend:** Vanilla JS/HTML/CSS (served locally or packaged via Tauri v2 for desktop).
- **Data Storage:** SQLite (for request history and environments) and decoupled flat JSON files (for collections).
- **Execution Engine:** HTTPX asynchronous dispatcher with variable interpolation and sandboxed Node.js `pm.*` script evaluation.

## 2. CLEAN-ROOM NATIVE STORAGE & INTEROPERABILITY
- **Decoupled Plain-Text Storage:** Collections persist using OpenPost's native schema (`https://openpost.dev/schema/v1/collection.json`) in `data/collections/`, providing human-readable, line-by-line diffable Git version control.
- **Postman v2.1.0 Interchange:** Collections can be imported from Postman v2.1.0 and exported back via `export_postman_collection` to strict Postman Collection v2.1.0 JSON.
- **Zero Cloud Mandate:** Stored 100% locally on user machine with zero external cloud telemetry or tracking.

## 3. AGENTIC MCP OPERATION
Every API testing workflow (Collection Import/Export, Folder/Request CRUD, Ad-hoc & Saved Request Execution, Collection Runner, Variable Interpolation, Environment Management, History Inspection) is exposed as 22 structured tools in `backend/mcp_server.py`.
