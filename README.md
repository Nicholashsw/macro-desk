# Macro Desk

A remote MCP server that gives Alexa+ a sell-side macro desk: ask about inflation, jobs, growth or rates and get a short spoken answer that tells you not just the number but whether it matters.

> "Alexa, how was the CPI print?"
>
> "Headline CPI inflation was 4.0 percent year on year in September 2026, up from 3.7 percent. The monthly change of 0.6 percent was a bigger than usual move, 1.9 standard deviations above its three-year average."

Most voice assistants read out a headline figure. Traders and anyone with a mortgage care about the next question: is that a big number? Macro Desk scores every release against its own recent history, so the answer to "was that unusual" is a z-score and a "largest since" date rather than an adjective.

## Tools

| Tool | Ask it | Returns |
|---|---|---|
| `macro_briefing` | "Brief me on the economy" | The releases that moved most against their history, curve shape, macro regime |
| `get_indicator` | "What was core PCE?" | Latest reading, prior reading, shock score when it is worth mentioning |
| `shock_score` | "Was the jobs number a surprise?" | z-score, historical percentile, last time a move this large happened |
| `yield_curve` | "Is the curve inverted?" | 3m, 2y, 10y yields, 10y-3m and 10y-2y spreads, regime start date, 1-month 10y move |
| `macro_regime` | "What regime are we in?" | Growth/inflation quadrant, months in regime, previous regime |
| `list_indicators` | "What can you track?" | Coverage and the phrases each indicator answers to |

Every result carries a `speech` field written to be read aloud verbatim (no symbols, one number per clause, no "sigma") plus the numbers behind it, so an agent can either speak or reason.

Indicators: headline and core CPI, core PCE, nonfarm payrolls, unemployment, retail sales, industrial production, initial jobless claims, real GDP, fed funds, 10-year breakevens and 3-month, 2-year and 10-year Treasury yields. Free-text names resolve through aliases and fuzzy matching, so "the jobs report", "nfp" and "payrolls" all land on the same series.

## Method

**Shock score.** For each indicator we separate the headline figure from the innovation, the new information in the latest print:

- Inflation and output (CPI, PCE, IP) are quoted year on year but scored on the month-on-month change, because the change in a YoY rate is dominated by base effects from twelve months ago.
- Rates and the unemployment rate are scored on the level change, payrolls on the print itself, GDP on the annualized quarterly rate.

The innovation is z-scored against the preceding three years of innovations (36 months, 156 weeks, 756 trading days or 12 quarters). The latest observation is excluded from its own mean and standard deviation. "Largest since" is the most recent earlier move at least as large in the same direction.

**Regime.** Growth momentum is the 3-month average of industrial production YoY minus the same average six months earlier; inflation momentum is the same on core CPI. The signs place the economy in one of four quadrants: goldilocks, reflation, stagflation or disinflationary slowdown.

**Data.** FRED via the public `fredgraph.csv` endpoint, so no API key is needed. All series are fetched in parallel at startup and refreshed in the background; a cold briefing touches twelve series and would otherwise take around ten seconds, which is longer than a voice turn allows. If FRED is unreachable each series falls back to the snapshot bundled in `macro_desk/data`, and every response reports `data_source: live | snapshot`.

## Run it

```bash
pip install -e ".[dev]"
python -m macro_desk.server          # http://localhost:8000/mcp
pytest
```

Open http://localhost:8000 for the voice console: speak or type a question and it calls the server over MCP exactly as Alexa+ would, showing the JSON-RPC traffic alongside the spoken answer. Voice input needs Chrome or Edge.

Environment variables:

| Variable | Default | |
|---|---|---|
| `HOST`, `PORT` | `0.0.0.0`, `8000` | |
| `MACRO_DESK_TOKEN` | unset | Require `Authorization: Bearer <token>` on `/mcp` |
| `MACRO_DESK_OFFLINE` | unset | `1` uses the bundled snapshot only |
| `MACRO_DESK_TTL` | `10800` | Cache lifetime in seconds |

The server speaks MCP over Streamable HTTP in stateless mode and negotiates protocol `2025-11-25` and later. `tests/test_server.py` drives the full handshake and every tool with raw JSON-RPC.

## Deploy on Amazon Bedrock AgentCore Runtime

AgentCore hosts MCP servers natively: it expects `0.0.0.0:8000/mcp`, stateless Streamable HTTP and ARM64, which is how this server runs by default.

```bash
npm install -g @aws/agentcore

# Cognito user pool for inbound auth: see deploy/agentcore/README.md
agentcore create --project-name MacroDesk --no-agent
cd MacroDesk
agentcore add agent --name MacroDesk --language Python --protocol MCP \
  --authorizer-type CUSTOM_JWT \
  --discovery-url "https://cognito-idp.$REGION.amazonaws.com/$POOL_ID/.well-known/openid-configuration" \
  --allowed-clients "$CLIENT_ID" --request-header-allowlist Authorization
cp -r ../macro_desk app/MacroDesk/
cp ../deploy/agentcore/main.py app/MacroDesk/main.py
(cd app/MacroDesk && uv add "mcp>=2.2,<3" pandas httpx uvicorn)
agentcore deploy
```

The endpoint is then

```
https://bedrock-agentcore.$REGION.amazonaws.com/runtimes/<url-encoded ARN>/invocations?qualifier=DEFAULT
```

A container image is also provided (`Dockerfile`, `linux/arm64`) for App Runner, ECS or anywhere else that runs containers.

## Connecting to Alexa+

Register the deployed `/mcp` URL as a remote MCP server in the Alexa+ developer preview. The server instructions tell the model to use `speech` verbatim and not to add numbers that are not in the result, which keeps the spoken answer grounded in the data.

## Layout

```
macro_desk/
  catalog.py     indicator definitions, aliases, free-text resolver
  data.py        FRED loader, cache, parallel refresh, snapshot fallback
  analytics.py   transforms, rolling z-scores, curve, regime (no I/O)
  speech.py      readings -> sentences for text-to-speech
  desk.py        the tool logic, independent of MCP
  server.py      MCP server, voice console, health check, bearer auth
  web/           browser voice console
  data/          FRED snapshot for offline use and tests
deploy/agentcore AgentCore Runtime entrypoint and setup notes
tests/
```

Data: Federal Reserve Bank of St. Louis, FRED. Licensed under MIT.
