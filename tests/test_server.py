"""End-to-end over Streamable HTTP, speaking raw JSON-RPC the way a remote client does."""

import json
import os

import pytest
from starlette.testclient import TestClient

os.environ["MACRO_DESK_OFFLINE"] = "1"

from macro_desk import server  # noqa: E402

PROTOCOL = "2025-11-25"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params=None, id_=1, headers=None):
    body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    resp = client.post("/mcp", content=json.dumps(body), headers={**HEADERS, **(headers or {})})
    assert resp.status_code == 200, resp.text
    if resp.headers["content-type"].startswith("text/event-stream"):
        data = [line[5:].strip() for line in resp.text.splitlines() if line.startswith("data:")]
        return json.loads(data[-1])
    return resp.json()


@pytest.fixture(scope="module")
def client():
    with TestClient(server.build_app(host="0.0.0.0", warm=False)) as c:
        init = rpc(c, "initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "0"}})
        assert init["result"]["protocolVersion"] == PROTOCOL
        c.headers["MCP-Protocol-Version"] = PROTOCOL
        yield c


def call(client, name, args=None):
    out = rpc(client, "tools/call", {"name": name, "arguments": args or {}}, id_=2)
    return out["result"]


def test_tools_listed(client):
    tools = {t["name"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert tools == {"macro_briefing", "get_indicator", "shock_score", "yield_curve", "macro_regime",
                     "list_indicators"}


@pytest.mark.parametrize("name,args", [
    ("macro_briefing", {}), ("get_indicator", {"indicator": "inflation"}),
    ("shock_score", {"indicator": "jobs report"}), ("yield_curve", {}), ("macro_regime", {}),
])
def test_tools_return_speech(client, name, args):
    result = call(client, name, args)
    assert not result.get("isError")
    payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert payload["speech"].endswith(".")
    assert "nan" not in payload["speech"].lower()


def test_unknown_indicator_is_a_tool_error(client):
    result = call(client, "get_indicator", {"indicator": "dogecoin"})
    assert result["isError"]
    assert "I can cover" in result["content"][0]["text"]


def test_ping():
    with TestClient(server.build_app(warm=False)) as c:
        assert c.get("/ping").json() == {"status": "ok"}
        assert "Macro" in c.get("/").text


def test_bearer_token(monkeypatch):
    monkeypatch.setenv("MACRO_DESK_TOKEN", "s3cret")
    with TestClient(server.build_app(warm=False)) as c:
        assert c.post("/mcp", content="{}", headers=HEADERS).status_code == 401
        assert c.get("/ping").status_code == 200
