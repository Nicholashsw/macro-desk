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

**Data.** FRED via the public `fredgraph.csv` endpoint, so no API key is needed. Requests never wait on the network: the cache is primed from a snapshot bundled in `macro_desk/data` and refreshed from FRED in the background, stale-while-revalidate. A cold start answers its first briefing in about 25 ms and switches to live data within seconds; if FRED is down the server keeps answering from the last good copy. Every response reports `data_source: live | snapshot`.

## Alexa+ compatibility

Alexa+ connects to MCP add-ons over Streamable HTTP, initializes at protocol `2025-03-26`, and expects a round trip under 500 ms. The server negotiates `2025-03-26` through `2025-11-25`, returns every result as both `structuredContent` and a JSON text block, and is covered by tests for each of those (`tests/test_server.py`, `tests/test_latency.py`). The data is public, so the endpoint needs no account linking.

## Run it

```bash
pip install -e ".[dev]"
python -m macro_desk.server          # http://localhost:8000/mcp
pytest
```

Open http://localhost:8000 for the voice console: speak or type a question and it calls the server over MCP, showing the JSON-RPC traffic alongside the spoken answer. Voice input needs Chrome or Edge.

| Variable | Default | |
|---|---|---|
| `HOST`, `PORT` | `0.0.0.0`, `8000` | |
| `MACRO_DESK_OFFLINE` | unset | `1` uses the bundled snapshot only |
| `MACRO_DESK_TTL` | `10800` | Seconds before a series is refreshed from FRED |
| `MACRO_DESK_TOKEN` | unset | Require `Authorization: Bearer <token>` on `/mcp` for private deployments |

The server also serves the add-on listing assets: `/privacy`, `/terms`, `/assets/icon-*.png` and `/assets/carousel-600x900.png` (regenerate with `scripts/make_assets.py`).

## Play it on Sonos

The same briefing can be spoken on a Sonos speaker from a Mac on the same Wi-Fi. Speech is rendered locally with macOS `say`, served from the Mac on one port, and played through [SoCo](https://github.com/SoCo/SoCo) over the speaker's local UPnP interface. No Sonos account or cloud API is involved, and whatever was playing resumes afterwards at its original volume.

```bash
pip install -e ".[sonos]"
macro-desk-sonos discover                  # list speakers, plays nothing
macro-desk-sonos say "Testing, one two"    # short test clip
macro-desk-sonos brief                     # the latest macro briefing
macro-desk-sonos brief --dry-run           # render the audio only
```

Playback asks before it starts; `--yes` skips the prompt. The first run triggers a macOS firewall prompt for Python: allow it, or the speaker cannot fetch the clip.

| Variable | Default | |
|---|---|---|
| `MACRO_DESK_SONOS_NAME` | unset | Room name, needed when there is more than one speaker |
| `MACRO_DESK_SONOS_IP` | unset | Skip discovery, for networks that block multicast |
| `MACRO_DESK_SONOS_VOLUME` | current | Volume for the clip, restored afterwards |
| `MACRO_DESK_CLIP_PORT` | `8765` | Port the clip is served on |
| `MACRO_DESK_VOICE`, `MACRO_DESK_RATE` | system | `say` voice and words per minute |
| `MACRO_DESK_AUDIO_DIR` | `~/.cache/macro-desk` | Rendered clips, last five kept |

For a weekday morning briefing, `scripts/macro-desk-briefing.plist` is a launchd template that runs `brief --yes --skip-if-playing` at 07:30. US releases land at 08:30 Eastern, which is the previous evening in Singapore, so a 07:30 briefing there covers the night's data. The Sonos path is local only and is not part of the server image.

## Deploy on AWS

`scripts/deploy_ecs.sh` builds an ARM64 image, pushes it to Amazon ECR and runs it on Amazon ECS Express Mode, which puts it behind an HTTPS load balancer with a URL of the form `https://<service>.ecs.<region>.on.aws`. One task stays up at all times, so there is no cold start for Alexa+ to wait through.

```bash
AWS_REGION=us-east-1 scripts/deploy_ecs.sh           # create or update
AWS_REGION=us-east-1 scripts/deploy_ecs.sh --delete  # tear down
```

## Connect to Alexa+

With the [Alexa AI CLI](https://developer.amazon.com/docs/alexaplus/add-ons/set-up-your-development-environment) installed and configured:

```bash
alexa-ai new mcp --name "Macro Desk" --locale en-US --mcp-server-url "https://<host>/mcp"
# copy descriptions, example phrases, policy URLs and media assets from alexa/listing.json
alexa-ai deploy
```

Then test in the Alexa+ web simulator from the developer console. Alexa+ reads tool definitions at deploy time, so run `alexa-ai deploy` again after changing tools.

## Layout

```
macro_desk/
  catalog.py     indicator definitions, aliases, free-text resolver
  data.py        FRED loader, cache, parallel refresh, snapshot fallback
  analytics.py   transforms, rolling z-scores, curve, regime (no I/O)
  speech.py      readings -> sentences for text-to-speech
  desk.py        the tool logic, independent of MCP
  server.py      MCP server, console, listing pages, health check
  tts.py         macOS speech rendering for local playback
  clipserver.py  one-file HTTP server the speaker fetches from
  sonos.py       speaker discovery and playback with resume
  sonos_cli.py   macro-desk-sonos command
  web/           voice console, privacy and terms pages, add-on art
  data/          FRED snapshot used to prime the cache and for tests
alexa/           Alexa+ add-on listing values
scripts/         ECS deploy, snapshot refresh, add-on art, launchd briefing
tests/
```

## License

MIT
