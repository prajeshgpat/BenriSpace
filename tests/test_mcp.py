"""MCP connector endpoint (api/mcp.py): JSON-RPC over POST /mcp, no database."""

import json

import pytest
from fastapi.testclient import TestClient

from api import mcp
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def rpc(client, method, params=None, id_=1, path="/mcp"):
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(path, json=body)


def test_initialize_negotiates_the_protocol_and_describes_the_server(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "benrispace"
    assert "New York metro" in result["instructions"]
    newer = rpc(client, "initialize", {"protocolVersion": "2099-01-01"}).json()["result"]
    assert newer["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]


def test_tools_list_has_the_chat_tools_plus_travel_area_and_triangulate(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"geocode", "area_score", "search_areas", "optimize_location"} <= names
    assert {"travel_area", "triangulate"} <= names
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["annotations"]["readOnlyHint"] is True
        assert t["description"]


def test_tools_call_returns_text_and_structured_content(client, monkeypatch):
    monkeypatch.setattr(
        mcp, "run_tool", lambda name, args, ctx: ({"latitude": 40.7, "query": args["query"]}, False)
    )
    r = rpc(client, "tools/call", {"name": "geocode", "arguments": {"query": "Hoboken"}})
    result = r.json()["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["query"] == "Hoboken"
    assert result["structuredContent"]["latitude"] == 40.7


def test_tool_failures_are_results_with_is_error(client, monkeypatch):
    def boom(args):
        raise mcp.ToolError("That location is outside the covered NYC metro area.")

    monkeypatch.setitem(mcp.EXTRA_IMPL, "travel_area", boom)
    r = rpc(
        client, "tools/call", {"name": "travel_area", "arguments": {"mode": "walk", "minutes": 10}}
    )
    result = r.json()["result"]
    assert result["isError"] is True
    assert "outside" in result["content"][0]["text"]
    assert "structuredContent" not in result


def test_protocol_errors(client):
    assert rpc(client, "nope").json()["error"]["code"] == -32601
    assert rpc(client, "tools/call", {"name": "drop_tables"}).json()["error"]["code"] == -32602
    bad = client.post("/mcp", content=b"{not json", headers={"content-type": "application/json"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700


def test_notifications_get_202_and_get_is_not_allowed(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""
    assert client.get("/mcp").status_code == 405
    assert rpc(client, "ping", path="/v1/mcp").json()["result"] == {}


def test_batches_answer_requests_and_skip_notifications(client):
    r = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 7, "method": "ping"},
        ],
    )
    assert r.json() == [{"jsonrpc": "2.0", "id": 7, "result": {}}]
