"""Critical-Path Test Suite for OpenPost:
1. Postman Collection v2.1.0 Ingest & Edge-Case Normalization
2. Clean-Room Native Plain-Text Collection Format & Schema Decoupling
3. Round-Trip Export to Postman v2.1.0 Format
4. String-Interpolation Engine (`{{var}}`, dynamic `{{$guid}}`, cycle safety)
5. Full Agentic MCP Server Tool Coverage (Collections, Requests, Runner, Environments, History)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend import mcp_server
from backend.collection_parser import (
    OPENPOST_COLLECTION_SCHEMA_V1,
    POSTMAN_SCHEMA_V2_1_0,
    export_to_openpost_native,
    export_to_postman_v21,
    parse_openpost_collection_dict,
    parse_postman_collection_dict,
)
from backend.local_db import LocalStore
from backend.request_engine import (
    build_variable_context,
    interpolate_string,
    prepare_http_request,
)


@pytest.fixture()
def isolated_store(tmp_path: Path) -> LocalStore:
    """Provide an isolated temporary LocalStore and bind it to `mcp_server`."""
    store = LocalStore(base_data_dir=tmp_path / "openpost_data")
    mcp_server.set_store(store)
    return store


SAMPLE_POSTMAN_V21_COLLECTION: dict[str, Any] = {
    "info": {
        "_postman_id": "2c8d1a90-5555-4b11-9999-abcdef123456",
        "name": "OpenPost CleanRoom API Suite",
        "description": {"content": "Sample Postman v2.1.0 collection with edge cases"},
        "schema": POSTMAN_SCHEMA_V2_1_0,
    },
    "variable": [
        {"key": "base_url", "value": "https://api.example.com", "type": "string"},
        {"key": "api_version", "value": "v2", "type": "string"},
    ],
    "auth": {
        "type": "bearer",
        "bearer": [{"key": "token", "value": "{{auth_token}}", "type": "string"}],
    },
    "item": [
        {
            "name": "Users Folder",
            "description": "User management endpoints",
            "item": [
                {
                    "id": "req-list-users",
                    "name": "List Users (Structured URL without raw)",
                    "request": {
                        "method": "GET",
                        "header": "X-Custom-Trace: {{$guid}}\nAccept: application/json",
                        "url": {
                            "protocol": "https",
                            "host": ["api", "example", "com"],
                            "path": ["{{api_version}}", "users"],
                            "query": [
                                {"key": "limit", "value": "25", "disabled": False},
                                {"key": "debug", "value": "true", "disabled": True},
                            ],
                        },
                    },
                },
                {
                    "id": "req-create-user",
                    "name": "Create User (POST JSON)",
                    "request": {
                        "method": "POST",
                        "header": [{"key": "Content-Type", "value": "application/json"}],
                        "body": {
                            "mode": "raw",
                            "raw": '{"username": "{{new_user}}", "role": "admin"}',
                            "options": {"raw": {"language": "json"}},
                        },
                        "url": {
                            "raw": "{{base_url}}/{{api_version}}/users",
                            "host": ["{{base_url}}"],
                            "path": ["{{api_version}}", "users"],
                        },
                    },
                },
            ],
        },
        {
            "id": "req-legacy-string",
            "name": "Healthcheck (Plain String Request Edge Case)",
            "request": "{{base_url}}/healthz?ping=1",
        },
    ],
}


def test_parse_postman_v21_collection_and_edge_cases() -> None:
    parsed = parse_postman_collection_dict(SAMPLE_POSTMAN_V21_COLLECTION)
    assert parsed.id == "2c8d1a90-5555-4b11-9999-abcdef123456"
    assert parsed.name == "OpenPost CleanRoom API Suite"
    assert len(parsed.variables) == 2
    assert len(parsed.folders) == 1
    assert parsed.folders[0].name == "Users Folder"
    assert len(parsed.requests) == 3

    # 1. Structured URL where `raw` was omitted by Postman exporter
    req1 = parsed.requests[0]
    assert req1.folder_path == ["Users Folder"]
    assert req1.raw_url == "https://api.example.com/{{api_version}}/users?limit=25"
    assert len(req1.headers) == 2
    assert req1.headers[0]["key"] == "X-Custom-Trace"
    # Auth inherited from collection root
    assert req1.auth == {"type": "bearer", "params": {"token": "{{auth_token}}"}}

    # 2. POST JSON request
    req2 = parsed.requests[1]
    assert req2.method == "POST"
    assert req2.body is not None
    assert req2.body["mode"] == "raw"
    assert '"{{new_user}}"' in req2.body["raw"]

    # 3. Plain-string request edge case
    req3 = parsed.requests[2]
    assert req3.method == "GET"
    assert req3.raw_url == "{{base_url}}/healthz?ping=1"
    assert req3.query_params == [{"key": "ping", "value": "1", "description": "", "disabled": False}]


def test_roundtrip_export_to_postman_v21() -> None:
    parsed = parse_postman_collection_dict(SAMPLE_POSTMAN_V21_COLLECTION)
    exported = export_to_postman_v21(parsed)
    assert exported["info"]["schema"] == POSTMAN_SCHEMA_V2_1_0
    reparsed = parse_postman_collection_dict(exported)
    assert reparsed.name == parsed.name
    assert len(reparsed.requests) == len(parsed.requests)
    assert reparsed.requests[1].body == parsed.requests[1].body


def test_variable_interpolation_and_cycle_safety() -> None:
    ctx = build_variable_context(
        collection_vars=[{"key": "base_url", "value": "https://{{host_domain}}/api"}],
        environment_vars=[{"key": "host_domain", "value": "local.openpost.dev"}],
        override_vars={"user_id": "42", "cycle_a": "{{cycle_b}}", "cycle_b": "{{cycle_a}}"},
    )

    unresolved: set[str] = set()
    url = interpolate_string(
        "{{base_url}}/users/{{user_id}}?trace={{$guid}}&missing={{unknown_var}}",
        ctx,
        unresolved,
    )
    assert url.startswith("https://local.openpost.dev/api/users/42?trace=")
    assert "unknown_var" in unresolved

    # Ensure cyclic variables terminate cleanly without infinite recursion
    cyclic = interpolate_string("{{cycle_a}}", ctx)
    assert cyclic in ("{{cycle_a}}", "{{cycle_b}}")


def test_prepare_http_request_with_auth_injection() -> None:
    prepared = prepare_http_request(
        method="post",
        raw_url="{{base_url}}/items",
        headers=[{"key": "X-Env", "value": "{{env_name}}"}],
        body={"mode": "raw", "raw": '{"item": "{{item_name}}"}', "language": "json"},
        auth={"type": "bearer", "params": {"token": "{{secret_jwt}}"}},
        variables={
            "base_url": "https://api.openpost.local",
            "env_name": "staging",
            "item_name": "widget",
            "secret_jwt": "tok_987654",
        },
    )
    assert prepared["method"] == "POST"
    assert prepared["url"] == "https://api.openpost.local/items"
    assert prepared["headers"]["Authorization"] == "Bearer tok_987654"
    assert prepared["headers"]["Content-Type"] == "application/json"
    assert prepared["content"] == '{"item": "widget"}'
    assert prepared["unresolved_variables"] == []


@pytest.mark.asyncio
async def test_mcp_server_end_to_end_agentic_workflow(isolated_store: LocalStore) -> None:
    # 1. Import collection via MCP tool
    imp = mcp_server.import_postman_collection(collection_json=SAMPLE_POSTMAN_V21_COLLECTION)
    col_id = imp["collection_id"]
    assert imp["request_count"] == 3

    # 2. Create environment & set variable via MCP tools
    env = mcp_server.save_environment(
        name="Production Mirror",
        variables={"auth_token": "mcp_secret_token", "new_user": "alice_agent"},
    )
    env_id = env["id"]
    mcp_server.set_environment_variable(env_id, "api_version", "v3")

    # 3. Preview interpolation via MCP tool
    preview = mcp_server.interpolate_preview(
        raw_url="{{base_url}}/{{api_version}}/users",
        collection_id=col_id,
        environment_id=env_id,
    )
    assert preview["url"] == "https://api.example.com/v3/users"

    # 4. Create folder & save a new request via MCP tools
    folder = mcp_server.create_folder(collection_id=col_id, name="Agentic Folder")
    assert folder["name"] == "Agentic Folder"

    saved_req = mcp_server.save_request(
        collection_id=col_id,
        name="Agent Created Endpoint",
        method="GET",
        raw_url="{{base_url}}/{{api_version}}/ping",
        folder_path=["Agentic Folder"],
    )
    assert saved_req["id"]

    # 5. Execute collection runner with mocked HTTP transport
    mock_http_result = {
        "ok": True,
        "status_code": 200,
        "reason_phrase": "OK",
        "elapsed_ms": 12.5,
        "size_bytes": 48,
        "url": "https://api.example.com/v3/ping",
        "headers": {"content-type": "application/json"},
        "body_text": '{"pong": true}',
        "body_json": {"pong": True},
        "prepared_request": {"method": "GET", "url": "https://api.example.com/v3/ping"},
    }
    with patch("backend.mcp_server.execute_http_request", new=AsyncMock(return_value=mock_http_result)):
        runner_report = await mcp_server.run_collection(
            collection_id=col_id,
            environment_id=env_id,
        )
        assert runner_report["total_requests"] == 4
        assert runner_report["passed"] == 4
        assert runner_report["failed"] == 0

    # 6. Verify history was logged and can be inspected & cleared via MCP tools
    history = mcp_server.list_request_history()
    assert len(history) == 4
    entry_detail = mcp_server.get_history_entry(history[0]["id"])
    assert entry_detail["response"]["status_code"] == 200

    cleared = mcp_server.clear_request_history()
    assert cleared["cleared_entries"] == 4


def test_native_clean_room_collection_storage_and_schema(isolated_store: LocalStore) -> None:
    """Verify clean-room native schema persists locally without Postman schema coupling."""
    col = isolated_store.create_collection(
        name="Native CleanRoom Suite",
        description="Local-first collection decoupled from proprietary schemas",
        variables=[{"key": "env", "value": "local"}],
    )
    col_id = col["id"]
    assert col["schema"] == OPENPOST_COLLECTION_SCHEMA_V1

    # Verify physical file on disk uses OpenPost schema
    disk_path = isolated_store._collection_path(col_id)
    assert disk_path.exists()
    disk_content = json.loads(disk_path.read_text(encoding="utf-8"))
    assert disk_content["schema"] == OPENPOST_COLLECTION_SCHEMA_V1
    assert "schema.postman.com" not in json.dumps(disk_content)

    # Add folder and request and verify schema remains OpenPost native
    isolated_store.add_folder(collection_id=col_id, name="Local Folder")
    isolated_store.upsert_request(
        collection_id=col_id,
        name="Local Endpoint",
        method="GET",
        raw_url="https://api.local/endpoint",
        folder_path=["Local Folder"],
    )
    updated = isolated_store.get_collection(col_id)
    assert updated is not None
    assert updated["schema"] == OPENPOST_COLLECTION_SCHEMA_V1
    assert len(updated["folders"]) == 1
    assert len(updated["requests"]) == 1


@pytest.mark.asyncio
async def test_fastapi_rest_parity(isolated_store: LocalStore) -> None:
    import httpx
    from backend.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mcp_tools_available"] == 22

        imp = await client.post(
            "/api/collections/import",
            json={"collection_json": SAMPLE_POSTMAN_V21_COLLECTION},
        )
        assert imp.status_code == 200
        col_id = imp.json()["collection_id"]

        cols = await client.get("/api/collections")
        assert len(cols.json()) == 1

        exp = await client.get(f"/api/collections/{col_id}/export")
        assert exp.status_code == 200
        assert exp.json()["collection"]["info"]["name"] == "OpenPost CleanRoom API Suite"


def test_legacy_scratchpad_payload_import() -> None:
    legacy_payload: dict[str, Any] = {
        "info": {
            "_postman_id": "112233-col-legacy",
            "name": "Legacy Scratch Pad Collection",
            "schema": POSTMAN_SCHEMA_V2_1_0,
        },
        "item": [
            {
                "uid": "123456-99999999-8888-7777-6666-555544443333",
                "name": "Legacy Raw Mode Request",
                "dataMode": "raw",
                "rawModeData": '{"legacy_token": "xyz"}',
                "headerData": [
                    {"key": "X-Legacy", "value": "true", "enabled": True},
                    {"key": "X-Disabled", "value": "skip", "enabled": False},
                ],
                "url": "https://api.example.com/legacy",
                "method": "post",
            }
        ],
    }

    parsed = parse_postman_collection_dict(legacy_payload)
    assert len(parsed.requests) == 1
    req = parsed.requests[0]
    assert req.name == "Legacy Raw Mode Request"
    assert req.method == "POST"
    assert req.id == "99999999-8888-7777-6666-555544443333"  # compound UID decomposed cleanly
    assert req.body == {"mode": "raw", "raw": '{"legacy_token": "xyz"}', "disabled": False, "language": "json"}
    assert req.headers == [
        {"key": "X-Legacy", "value": "true", "description": "", "disabled": False},
        {"key": "X-Disabled", "value": "skip", "description": "", "disabled": True},
    ]


def test_decoupled_import_and_export_roundtrip(isolated_store: LocalStore) -> None:
    """Verify Postman v2.1.0 can be imported, stored natively, and exported back cleanly."""
    imported = isolated_store.import_postman_json(SAMPLE_POSTMAN_V21_COLLECTION)
    col_id = imported["id"]

    # In local storage, schema is decoupled to OpenPost native
    stored = isolated_store.get_collection(col_id)
    assert stored is not None
    assert stored["schema"] == OPENPOST_COLLECTION_SCHEMA_V1

    # Export to Postman v2.1.0 format
    exported_v21 = isolated_store.export_collection_v21(col_id)
    assert exported_v21 is not None
    assert exported_v21["info"]["schema"] == POSTMAN_SCHEMA_V2_1_0
    assert exported_v21["info"]["name"] == "OpenPost CleanRoom API Suite"
    assert len(exported_v21["item"]) == 2  # Users Folder + Healthcheck item

    # Native export maintains native schema
    exported_native = isolated_store.export_collection_native(col_id)
    assert exported_native is not None
    assert exported_native["schema"] == OPENPOST_COLLECTION_SCHEMA_V1

    # Re-import exported Postman payload into parser
    reparsed = parse_postman_collection_dict(exported_v21)
    assert reparsed.name == "OpenPost CleanRoom API Suite"
    assert len(reparsed.requests) == 3


def test_native_plain_text_collection_parser() -> None:
    """Verify direct parsing and serialization of OpenPost native plain-text JSON format."""
    native_payload: dict[str, Any] = {
        "id": "native-col-001",
        "name": "Native OpenPost Suite",
        "description": "Clean-room schema test",
        "schema": OPENPOST_COLLECTION_SCHEMA_V1,
        "variables": [{"key": "port", "value": "8080"}],
        "auth": {"type": "bearer", "params": {"token": "secret"}},
        "folders": [
            {"id": "fld-1", "name": "V1", "folder_path": []}
        ],
        "requests": [
            {
                "id": "req-1",
                "name": "Ping",
                "method": "GET",
                "raw_url": "http://localhost:{{port}}/ping",
                "folder_path": ["V1"],
                "headers": [{"key": "Accept", "value": "text/plain"}],
                "query_params": [],
                "path_variables": [],
            }
        ],
    }

    parsed = parse_openpost_collection_dict(native_payload)
    assert parsed.id == "native-col-001"
    assert parsed.schema == OPENPOST_COLLECTION_SCHEMA_V1
    assert len(parsed.folders) == 1
    assert len(parsed.requests) == 1
    assert parsed.requests[0].raw_url == "http://localhost:{{port}}/ping"

    # Exporting native collection to Postman v2.1.0 should map correctly
    exported = export_to_postman_v21(parsed)
    assert exported["info"]["schema"] == POSTMAN_SCHEMA_V2_1_0
    assert exported["info"]["name"] == "Native OpenPost Suite"
    assert len(exported["item"]) == 1  # V1 folder containing Ping request


def test_production_collections_clean_room_schema_compliance() -> None:
    """Verify checked-in production collections use OpenPost native schema without contamination."""
    collections_dir = Path(__file__).resolve().parent.parent / "data" / "collections"
    col_files = list(collections_dir.glob("*.json"))
    assert len(col_files) >= 2, f"Expected production collections in {collections_dir}, found {len(col_files)}"
    for col_file in col_files:
        data = json.loads(col_file.read_text(encoding="utf-8"))
        assert data.get("schema") == OPENPOST_COLLECTION_SCHEMA_V1, (
            f"File {col_file.name} does not declare OpenPost native schema"
        )
        assert "schema.postman.com" not in json.dumps(data), (
            f"File {col_file.name} contains proprietary schema reference"
        )


def test_path_and_dynamic_variables() -> None:
    from backend.request_engine import build_variable_context, prepare_http_request

    ctx = build_variable_context(
        environment_vars=[{"key": "base_url", "value": "https://api.test.local"}],
    )

    # Path variable :userId resolved via path_variables
    prep = prepare_http_request(
        method="GET",
        raw_url="{{base_url}}/accounts/:accountId/users/:userId?email={{$randomEmail}}&uuid={{$randomUUID}}&flag={{$randomBoolean}}",
        path_variables=[
            {"key": "accountId", "value": "acc_777"},
            {"key": "userId", "value": "usr_999"},
        ],
        variables=ctx,
    )

    assert prep["url"].startswith("https://api.test.local/accounts/acc_777/users/usr_999?email=")
    assert "@example.com" in prep["url"]
    assert "flag=true" in prep["url"] or "flag=false" in prep["url"]


@pytest.mark.asyncio
async def test_postman_script_runner() -> None:
    from backend.script_runner import run_postman_script_async

    pr_script = """
    pm.environment.set("auth_header", "Bearer dyn_token_777");
    pm.collectionVariables.set("trace_id", "trc_999");
    console.log("Pre-request script executed");
    """
    pr_res = await run_postman_script_async(
        script=pr_script,
        listen="prerequest",
        environment={"base_url": "https://api.dev"},
        collection_variables={},
    )
    assert pr_res["ok"] is True
    assert pr_res["updated_environment"]["auth_header"] == "Bearer dyn_token_777"
    assert pr_res["updated_collection_variables"]["trace_id"] == "trc_999"

    test_script = """
    pm.test("Status code is 200", function () {
        pm.response.to.have.status(200);
    });
    pm.test("Response contains user", function () {
        pm.expect(pm.response.json().user.name).to.equal("Alice");
    });
    pm.test("Should fail on purpose", function () {
        pm.expect(pm.response.json().user.name).to.equal("Bob");
    });
    """
    test_res = await run_postman_script_async(
        script=test_script,
        listen="test",
        response={"status_code": 200, "body_text": '{"user": {"name": "Alice"}}'},
    )
    assert test_res["ok"] is True
    results = test_res["test_results"]
    assert len(results) == 3
    assert results[0]["passed"] is True
    assert results[1]["passed"] is True
    assert results[2]["passed"] is False
    assert 'expected "Alice" to equal "Bob"' in results[2]["error"]


@pytest.mark.asyncio
async def test_collection_runner_with_prerequest_and_test_scripts(isolated_store: LocalStore) -> None:
    from unittest.mock import AsyncMock, patch

    col_payload = {
        "info": {
            "_postman_id": "col-script-runner-01",
            "name": "Scripted API Suite",
            "schema": POSTMAN_SCHEMA_V2_1_0,
        },
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": ["pm.environment.set('calc_id', 'id_555');"],
                },
            }
        ],
        "item": [
            {
                "id": "req-scripted-01",
                "name": "Scripted Ping",
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                "pm.test('Check status', () => pm.response.to.have.status(200));",
                                "pm.environment.set('session_token', pm.response.json().token);",
                            ],
                        },
                    }
                ],
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/items/{{calc_id}}",
                },
            }
        ],
    }

    imp = mcp_server.import_postman_collection(collection_json=col_payload)
    col_id = imp["collection_id"]
    env = mcp_server.save_environment(name="Script Env", variables={"calc_id": "initial"})
    env_id = env["id"]

    mock_resp = {
        "ok": True,
        "status_code": 200,
        "reason_phrase": "OK",
        "elapsed_ms": 15.0,
        "size_bytes": 35,
        "url": "https://api.example.com/items/id_555",
        "headers": {"content-type": "application/json"},
        "body_text": '{"token": "tok_extracted_123"}',
        "body_json": {"token": "tok_extracted_123"},
        "prepared_request": {"method": "GET", "url": "https://api.example.com/items/id_555"},
    }

    with patch("backend.mcp_server.execute_http_request", new=AsyncMock(return_value=mock_resp)):
        run_res = await mcp_server.run_collection(collection_id=col_id, environment_id=env_id)
        assert run_res["total_requests"] == 1
        assert run_res["passed"] == 1
        assert run_res["failed"] == 0

        # Verify environment variable was extracted by test script and saved back
        updated_env = mcp_server.get_environment(env_id)
        var_dict = {v["key"]: v["value"] for v in updated_env["variables"]}
        assert var_dict.get("session_token") == "tok_extracted_123"
        assert var_dict.get("calc_id") == "id_555"


def test_native_plain_text_null_fields_robustness() -> None:
    """Verify parse_openpost_collection_dict handles explicit None/null values gracefully."""
    payload: dict[str, Any] = {
        "id": "null-test-col",
        "name": "Null Edge Case Suite",
        "description": None,
        "schema": OPENPOST_COLLECTION_SCHEMA_V1,
        "variables": None,
        "folders": None,
        "requests": None,
        "raw_events": None,
    }
    parsed = parse_openpost_collection_dict(payload)
    assert parsed.name == "Null Edge Case Suite"
    assert parsed.variables == []
    assert parsed.folders == []
    assert parsed.requests == []
    assert parsed.raw_events == []

    # Also test null attributes inside requests and folders
    payload_with_null_children: dict[str, Any] = {
        "name": "Null Children Suite",
        "folders": [
            {
                "id": "fld-null",
                "name": "Null Folder",
                "folder_path": None,
                "description": None,
                "auth": None,
            }
        ],
        "requests": [
            {
                "id": "req-null",
                "name": "Null Request",
                "method": "get",
                "raw_url": "https://api.example.com",
                "folder_path": None,
                "headers": None,
                "query_params": None,
                "path_variables": None,
                "events": None,
            }
        ],
    }
    parsed2 = parse_openpost_collection_dict(payload_with_null_children)
    assert len(parsed2.folders) == 1
    assert parsed2.folders[0].folder_path == []
    assert len(parsed2.requests) == 1
    assert parsed2.requests[0].folder_path == []
    assert parsed2.requests[0].headers == []
    assert parsed2.requests[0].query_params == []
    assert parsed2.requests[0].path_variables == []
    assert parsed2.requests[0].events == []


def test_folder_auth_roundtrip_fidelity() -> None:
    """Verify folder-level authentication is preserved when exporting to Postman v2.1.0."""
    native_with_folder_auth: dict[str, Any] = {
        "name": "Folder Auth Suite",
        "schema": OPENPOST_COLLECTION_SCHEMA_V1,
        "folders": [
            {
                "id": "fld-auth",
                "name": "Secure V1",
                "folder_path": [],
                "auth": {
                    "type": "bearer",
                    "params": {"token": "secret_folder_bearer_token"},
                },
            }
        ],
        "requests": [
            {
                "id": "req-in-fld",
                "name": "Secured Endpoint",
                "method": "GET",
                "raw_url": "https://api.example.com/v1/secure",
                "folder_path": ["Secure V1"],
            }
        ],
    }
    parsed = parse_openpost_collection_dict(native_with_folder_auth)
    exported_v21 = export_to_postman_v21(parsed)

    folder_item = exported_v21["item"][0]
    assert folder_item["name"] == "Secure V1"
    assert "auth" in folder_item
    assert folder_item["auth"]["type"] == "bearer"
    assert folder_item["auth"]["bearer"] == [
        {"key": "token", "value": "secret_folder_bearer_token", "type": "string"}
    ]

    # Re-import and verify folder auth was retained
    reimported = parse_postman_collection_dict(exported_v21)
    assert len(reimported.folders) == 1
    assert reimported.folders[0].auth == {
        "type": "bearer",
        "params": {"token": "secret_folder_bearer_token"},
    }


def test_upsert_request_preserves_scripts_and_path_variables(isolated_store: LocalStore) -> None:
    """Verify updating a request preserves pre-request/test scripts and path variables."""
    col = isolated_store.create_collection("Script Preserving Suite")
    col_id = col["id"]

    # Save initial request with pre-request and test scripts
    req = isolated_store.upsert_request(
        collection_id=col_id,
        name="Get Profile",
        method="GET",
        raw_url="https://api.example.com/users/:uid",
        events=[
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": ["pm.test('Status is 200', () => pm.response.to.have.status(200));"],
                },
            }
        ],
        path_variables=[{"key": "uid", "value": "123"}],
    )
    req_id = req["id"]
    assert len(req["events"]) == 1
    assert len(req["path_variables"]) == 1

    # Update only the URL and name (as in a typical rename / Ctrl+S in the UI)
    updated = isolated_store.upsert_request(
        collection_id=col_id,
        request_id=req_id,
        name="Get Profile (Updated)",
        method="GET",
        raw_url="https://api.example.com/v2/users/:uid",
    )
    assert updated["name"] == "Get Profile (Updated)"
    assert updated["raw_url"] == "https://api.example.com/v2/users/:uid"
    # Verify scripts and path variables were NOT wiped
    assert len(updated["events"]) == 1
    assert updated["events"][0]["listen"] == "test"
    assert len(updated["path_variables"]) == 1
    assert updated["path_variables"][0]["key"] == "uid"


@pytest.mark.asyncio
async def test_chai_property_assertions_and_unset_persistence(isolated_store: LocalStore) -> None:
    """Verify pm.expect().to.be.true/false/null property getters and pm.environment.unset()."""
    from backend.script_runner import run_postman_script_async

    script = """
    pm.test("Property getter assertions work", function () {
        pm.expect(true).to.be.true;
        pm.expect(false).to.be.false;
        pm.expect(null).to.be.null;
        pm.expect(false).to.not.be.true;
    });
    pm.test("False property assertion fails when actual is false", function () {
        pm.expect(false).to.be.true;
    });
    pm.environment.unset("remove_me");
    """
    res = await run_postman_script_async(
        script=script,
        listen="test",
        environment={"remove_me": "123", "keep_me": "456"},
    )
    assert res["ok"] is True
    assert res["test_results"][0]["passed"] is True
    assert res["test_results"][1]["passed"] is False
    assert "remove_me" not in res["updated_environment"]
    assert res["updated_environment"]["keep_me"] == "456"


def test_inline_query_params_and_graphql_variables_serialization() -> None:
    """Verify inline URL query params are merged with explicit query_params and GraphQL variables parse to dict."""
    prep = prepare_http_request(
        method="POST",
        raw_url="https://api.example.com/graphql?inline=1#section",
        query_params=[{"key": "explicit", "value": "2"}],
        body={
            "mode": "graphql",
            "graphql": {
                "query": "query GetUser($id: ID!) { user(id: $id) { name } }",
                "variables": '{"id": "{{user_id}}"}',
            },
        },
        variables={"user_id": "u_42"},
    )
    assert prep["url"] == "https://api.example.com/graphql#section"
    assert prep["params"] == [("inline", "1"), ("explicit", "2")]
    body_json = json.loads(prep["content"])
    assert body_json["variables"] == {"id": "u_42"}


@pytest.mark.asyncio
async def test_sandbox_isolation_and_response_status_phrase() -> None:
    """Verify VM sandbox blocks access to process/require/eval/Function and maps reason_phrase to pm.response.status."""
    from backend.script_runner import run_postman_script_async

    script = """
    pm.test("pm.response.status is populated from reason_phrase", function () {
        pm.expect(pm.response.status).to.equal("Created");
    });
    pm.test("Node globals are isolated", function () {
        pm.expect(typeof process).to.equal("undefined");
        pm.expect(typeof require).to.equal("undefined");
        pm.expect(typeof fetch).to.equal("undefined");
    });
    pm.test("Dynamic code generation via constructor traversal is blocked", function () {
        var escaped = false;
        try {
            var fn = pm.expect(1).constructor.constructor("return typeof process");
            if (fn() !== "undefined") {
                escaped = true;
            }
        } catch (e) {
            escaped = false;
        }
        pm.expect(escaped).to.be.false;
    });
    """
    res = await run_postman_script_async(
        script=script,
        listen="test",
        response={"status_code": 201, "reason_phrase": "Created", "body_text": "{}"},
    )
    assert res["ok"] is True
    assert all(t["passed"] for t in res["test_results"]), f"Sandbox test failed: {res['test_results']}"


@pytest.mark.asyncio
async def test_security_cors_host_and_path_restrictions(isolated_store: LocalStore) -> None:
    """Verify CORS blocks external origins, TrustedHost blocks DNS rebinding, and file path traversal is rejected."""
    import httpx
    from backend.main import app
    from backend.request_engine import execute_http_request

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. External origin must not receive permissive Access-Control-Allow-Origin
        cors_evil = await client.get("/api/collections", headers={"Origin": "https://evil.example.com"})
        assert cors_evil.headers.get("access-control-allow-origin") is None

        # Localhost origin is allowed
        cors_local = await client.get("/api/collections", headers={"Origin": "http://127.0.0.1:8000"})
        assert cors_local.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"

        # 2. Arbitrary file_path outside workspace over HTTP is rejected
        bad_import = await client.post(
            "/api/collections/import",
            json={"file_path": "C:/Windows/win.ini"},
        )
        assert bad_import.status_code == 400

    # 3. DNS rebinding / untrusted Host header is rejected with 400
    async with httpx.AsyncClient(transport=transport, base_url="http://evil.rebind.attacker.com") as evil_client:
        rebind_res = await evil_client.get("/api/health")
        assert rebind_res.status_code == 400

    # 4. Invalid collection_id with only traversal punctuation raises ValueError
    with pytest.raises(ValueError, match="Invalid collection_id"):
        isolated_store._collection_path("../../..")

    # 5. Unsupported URL scheme (e.g. file://) is rejected in execute_http_request
    scheme_res = await execute_http_request(method="GET", raw_url="file:///etc/passwd")
    assert scheme_res["ok"] is False
    assert "Unsupported or missing URL scheme" in scheme_res["error"]


@pytest.mark.asyncio
async def test_folder_and_collection_auth_inheritance_with_noauth_request(isolated_store: LocalStore) -> None:
    """Verify requests with noauth inherit folder-level or collection-level authentication."""
    col = isolated_store.save_collection(
        {
            "id": "auth-inherit-col",
            "name": "Auth Inheritance Suite",
            "auth": {"type": "bearer", "params": {"token": "col_level_token"}},
            "folders": [
                {
                    "id": "fld-sec",
                    "name": "FolderWithAuth",
                    "folder_path": [],
                    "auth": {"type": "bearer", "params": {"token": "folder_level_token"}},
                }
            ],
            "requests": [
                {
                    "id": "req-in-folder",
                    "name": "Folder Request",
                    "method": "GET",
                    "raw_url": "https://api.example.com/folder-resource",
                    "folder_path": ["FolderWithAuth"],
                    "auth": {"type": "noauth", "params": {}},
                },
                {
                    "id": "req-at-root",
                    "name": "Root Request",
                    "method": "GET",
                    "raw_url": "https://api.example.com/root-resource",
                    "folder_path": [],
                    "auth": {"type": "noauth", "params": {}},
                },
            ],
        }
    )

    captured_auths: list[Any] = []

    async def fake_execute(**kwargs: Any) -> dict[str, Any]:
        captured_auths.append(kwargs.get("auth"))
        return {
            "ok": True,
            "status_code": 200,
            "reason_phrase": "OK",
            "elapsed_ms": 5.0,
            "size_bytes": 2,
            "url": kwargs["raw_url"],
            "headers": {},
            "body_text": "{}",
            "body_json": {},
            "prepared_request": {"method": "GET", "url": kwargs["raw_url"]},
        }

    with patch("backend.mcp_server.execute_http_request", side_effect=fake_execute):
        await mcp_server.run_collection(collection_id=col["id"])

    assert captured_auths[0] == {"type": "bearer", "params": {"token": "folder_level_token"}}
    assert captured_auths[1] == {"type": "bearer", "params": {"token": "col_level_token"}}







