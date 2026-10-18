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


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25"])
def test_negotiates_alexa_and_current_versions(version):
    # Alexa+ initializes at 2025-03-26; the hackathon requires 2025-11-25 support.
    with TestClient(server.build_app(warm=False)) as c:
        init = rpc(c, "initialize", {"protocolVersion": version, "capabilities": {"roots": {"listChanged": True}},
                                     "clientInfo": {"name": "Alexa+ MCP Client", "version": "1.0.0"}})
        assert init["result"]["protocolVersion"] == version
        c.headers["MCP-Protocol-Version"] = version
        result = call(c, "get_indicator", {"indicator": "core cpi"})
        assert result["structuredContent"]["speech"]


@pytest.mark.parametrize("name,args", [
    ("macro_briefing", {}), ("get_indicator", {"indicator": "inflation"}),
    ("shock_score", {"indicator": "jobs report"}), ("yield_curve", {}), ("macro_regime", {}),
])
def test_tools_return_speech(client, name, args):
    result = call(client, name, args)
    assert not result.get("isError")
    payload = result["structuredContent"]
    assert json.loads(result["content"][0]["text"]) == payload
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
        assert "Privacy Policy" in c.get("/privacy").text
        assert "Terms of Use" in c.get("/terms").text


@pytest.mark.parametrize("name", ["icon-64.png", "icon-72.png", "icon-88.png", "icon-126.png",
                                  "icon-180.png", "icon-241.png", "carousel-600x900.png"])
def test_addon_assets(name):
    with TestClient(server.build_app(warm=False)) as c:
        resp = c.get(f"/assets/{name}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"


def test_assets_do_not_escape_their_folder():
    with TestClient(server.build_app(warm=False)) as c:
        assert c.get("/assets/..%2Findex.html").status_code == 404
        assert c.get("/assets/missing.png").status_code == 404


def test_bearer_token(monkeypatch):
    monkeypatch.setenv("MACRO_DESK_TOKEN", "s3cret")
    with TestClient(server.build_app(warm=False)) as c:
        assert c.post("/mcp", content="{}", headers=HEADERS).status_code == 401
        assert c.get("/ping").status_code == 200
