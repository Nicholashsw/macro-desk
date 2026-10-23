# Friction log

| # | Task | Expected | Actual | Severity | Workaround | Suggestion |
|---|---|---|---|---|---|---|
| 1 | Follow "Deploy MCP servers in AgentCore Runtime" | The sample server and client run | `pip install mcp` installs 2.x; `from mcp.server.fastmcp import FastMCP` raises `ModuleNotFoundError` and `streamablehttp_client` raises `ImportError` | High | Ported to `MCPServer` with stateless Streamable HTTP | Pin `mcp<2` in the guide now, then publish 2.x samples |
| 2 | Host the Alexa+ add-on's MCP server on AgentCore Runtime | Alexa+ can call an AgentCore MCP endpoint | AgentCore requires SigV4 or JWT and returns 401 with `WWW-Authenticate`, which the Alexa+ toolkit lists as unsupported; Alexa+ also expects `/.well-known/oauth-authorization-server` | High | Amazon ECS Express Mode with an open endpoint, since the data is public | A reference architecture or auth mode for AgentCore + Alexa+ |
| 3 | Meet the track's MCP spec 2025-11-25+ requirement | Alexa+ negotiates a recent spec version | The Alexa+ client initializes at `2025-03-26` | Medium | Negotiate 2025-03-26 through 2025-11-25, with a test for each | State supported protocol versions in the MCP Toolkit quickstart |
| 4 | Decide whether a public, read-only server needs auth | Docs say whether auth is optional | The authentication page describes two tiers but never says public servers may skip auth | Low to medium | Shipped without auth | One sentence stating public servers may be unauthenticated |
| 5 | Answer within Alexa+'s 500 ms budget | Upstream data fits the budget | A cold briefing touching twelve FRED series took 13 s serially | Medium | Stale-while-revalidate cache primed from a bundled snapshot; about 25 ms on a cold start | A latency-patterns section in the MCP design guide |
