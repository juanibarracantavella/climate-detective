# Climate Detective: contributor guide

## Goal

Build a small, demo-ready proof of concept that turns Home Assistant sensor history into a short human-readable account of a selected period.

The pipeline is:

1. Resolve a requested period in the home's timezone.
2. Fetch allowlisted temperature, humidity, and power/energy entities from Home Assistant.
3. Normalize and reduce the time series deterministically.
4. Calculate statistics and detect sensor events.
5. Send only those derived facts to an LLM served by a Nebius Serverless AI endpoint.
6. Return the summary, facts, interval, and warnings to a vanilla JavaScript UI.

This is a hackathon PoC. Prefer a clear vertical slice over queues, databases, user accounts, or a generic analytics framework.

## Current handoff state

The first vertical slice is implemented and working:

- FastAPI serves both the API and the vanilla JavaScript frontend.
- `GET /api/home-sensors` has been exercised against the real Home Assistant instance and successfully returns current readings for all seven allowlisted sensors.
- `GET /api/summary?period=today|yesterday|last_7_days` fetches Home Assistant history for the configured indoor temperature, indoor humidity, and total power entities, performs deterministic analysis, and returns a summary.
- Temperature and humidity events are emitted as separate rise/drop timelines with start, end, and signed change. Significant swings use threshold-based turning points; calmer series are split into up to three periods around the overall low and high. The two sensor timelines may overlap because they describe independent measurements.
- The frontend displays each event's amount and full start/end interval.
- The Nebius adapter calls an OpenAI-compatible `/v1/chat/completions` endpoint when configured. With no key, or on an inference failure, it uses a deterministic local text fallback.
- The last verification run passed Ruff formatting/linting and all 20 tests.
- The implementation is currently an uncommitted worktree with many new files. Preserve it; do not clean or reset untracked files.

Important distinction: `/api/home-sensors` intentionally uses Home Assistant's `/api/states/{entity_id}` endpoint and therefore returns one current value per sensor. Historical series use `/api/history/period/<start>`. There is not yet an API endpoint that exposes raw historical series, and the current frontend only displays the summary response.

The local `.env` exists and is gitignored. It may contain a real Home Assistant token: never print, inspect unnecessarily, commit, or copy it into logs or responses. `.env.example` must remain secret-free.

## Local workflow

From the repository root:

```bash
make setup    # only needed to create/update .venv
make run      # backend + frontend on http://127.0.0.1:8000
make check    # Ruff lint, formatting check, and tests
```

Useful URLs:

- Frontend: `http://127.0.0.1:8000/`
- OpenAPI UI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/health`
- Current sensors: `http://127.0.0.1:8000/api/home-sensors`
- Summary: `http://127.0.0.1:8000/api/summary?period=today`

## Recommended architecture

Use one Python 3.12+ FastAPI application and serve the static frontend from it. Keeping frontend and API on one origin avoids unnecessary CORS and deployment work.

Suggested layout:

```text
app/
  main.py              # FastAPI routes and static files
  config.py            # validated environment configuration
  models.py            # API/domain models
  periods.py           # timezone-aware period resolution
  home_assistant.py    # Home Assistant REST adapter
  analysis.py          # pure normalization/statistics/event detection
  summarizer.py        # Nebius/OpenAI-compatible LLM adapter
static/
  index.html
  app.js
  styles.css
tests/
  fixtures/
  test_periods.py
  test_analysis.py
  test_api.py
```

Keep integrations behind small interfaces so tests can use fixtures and fakes. The analysis layer must not make network calls and the API route must not contain signal-processing logic.

## API contract

Start with one endpoint:

```http
GET /api/summary?period=today
```

Current Home Assistant readings are also exposed from the backend through:

```http
GET /api/home-sensors
```

This endpoint uses a fixed entity allowlist and reports errors per sensor so one missing or unavailable entity does not hide the remaining current readings.

The current-state allowlist is defined in `app/config.py`:

```text
sensor.meteo_aqara_balcony_temperature
sensor.meteo_aqara_balcony_humidity
sensor.abs_hum_balcony
sensor.average_indoor_temperature
sensor.average_indoor_humidity
sensor.average_indoor_abs_hum
sensor.total_power_meter_power
```

The normalized current-state item contains `entity_id`, numeric `value` when conversion is possible, original `raw_state`, `unit`, `friendly_name`, `last_changed`, `last_updated`, and `error`. Fetches run concurrently. Any individual timeout, HTTP error, or invalid response becomes that sensor's `error`; other readings are still returned.

Supported presets should initially be `today`, `yesterday`, and `last_7_days`. Add explicit `start` and `end` only if the UI needs them. Reject unknown periods with HTTP 422.

Return a stable shape such as:

```json
{
  "period": {"start": "2026-06-23T00:00:00+02:00", "end": "2026-06-24T00:00:00+02:00"},
  "summary": "The home stayed comfortable...",
  "events": [
    {"kind": "temperature_rise", "start": "...", "end": "...", "change": 2.1, "unit": "°C"}
  ],
  "statistics": {"temperature_mean": 21.4, "humidity_mean": 48.2, "energy_kwh": 5.7},
  "warnings": [],
  "generated_at": "2026-06-24T12:00:00Z"
}
```

Include derived facts in the response so the demo is inspectable and useful even when the LLM is unavailable. On LLM failure, return a deterministic fallback summary with a warning rather than failing the whole request. Use a short in-memory TTL cache keyed by the resolved interval; this limits repeated Home Assistant reads and paid inference during a demo.

## Home Assistant integration

Use the REST history endpoint:

```text
GET /api/history/period/<start>
  ?end_time=<end>
  &filter_entity_id=<comma-separated allowlist>
  &minimal_response
  &no_attributes
```

Send `Authorization: Bearer <token>`. Entity IDs come only from configuration, never from browser input. Set connection/read timeouts and produce a useful error for unreachable Home Assistant, 401, missing entities, or an empty interval.

Expected configuration:

```dotenv
HA_BASE_URL=https://home.cosasdejuan.es
HA_TOKEN=...
HA_TEMPERATURE_ENTITY=sensor.average_indoor_temperature
HA_HUMIDITY_ENTITY=sensor.average_indoor_humidity
HA_POWER_ENTITY=sensor.total_power_meter_power
HA_POWER_KIND=power
HA_TEMPERATURE_UNIT=°C
HA_HUMIDITY_UNIT=%
HA_POWER_UNIT=W
HOME_TIMEZONE=<the home's IANA timezone, for example Europe/Madrid>

NEBIUS_BASE_URL=http://<endpoint-address>/v1
NEBIUS_API_KEY=...
NEBIUS_MODEL=Qwen/Qwen3-0.6B
```

Do not assume sensor units. Make expected units explicit in configuration when using `no_attributes`; alternatively, omit that optimization and inspect response attributes. Validate the received/configured unit before analysis. Treat `unknown`, `unavailable`, non-numeric values, duplicate timestamps, and large gaps as missing data.

Power and energy are different:

- A power entity in W is instantaneous; estimate energy by time integration and report kWh.
- An energy entity in kWh is cumulative; usage is the interval delta, accounting for meter resets.

Name models and fields accordingly; never label an average power value as energy usage.

## Analysis rules

All calculations must be deterministic and covered by tests.

- Parse timestamps as timezone-aware values and sort samples.
- Resolve calendar presets in `HOME_TIMEZONE`, including daylight-saving transitions; use half-open intervals `[start, end)`.
- Resample noisy readings into configurable 15-minute bins. Use the mean for environmental values and time-weighted integration for power.
- Calculate count, coverage, minimum, maximum, and mean for temperature and humidity.
- Detect rises/drops from the smoothed series, not individual raw samples. Significant temperature and humidity swings use hysteresis around local extrema, with configured thresholds of 1.5 °C and 8 percentage points respectively. If a non-flat series never reaches its threshold, divide it into at most three rise/drop periods using its endpoints and overall low/high so a calm day's shape remains visible.
- Temperature and humidity form independent event sequences. Their events can overlap each other, while events within one sensor sequence are consecutive and must not overlap.
- Detect a power spike when a binned value is at least the configured threshold (initially 1000 W) above the median power for the selected interval.
- Keep thresholds in configuration, not as scattered magic numbers, and cap the facts sent to the LLM/API to 20 chronologically sorted events.
- Report insufficient coverage instead of inventing a conclusion.

Do not ask the LLM to calculate statistics or discover events. It is a wording layer only.

## LLM integration

Nebius Serverless AI can run a vLLM container as an interactive endpoint exposing the OpenAI-compatible `/v1/chat/completions` API. Keep the base URL, token, and model configurable; do not hard-code an endpoint IP or model.

Use a low temperature and a concise system prompt. Send structured derived facts with explicit units and timestamps. Instruct the model to:

- use only supplied facts;
- avoid guessing causes, occupancy, appliance identity, or safety issues;
- mention missing data when relevant;
- produce a brief household-friendly summary;
- not give medical, electrical, or safety assurances.

Put a strict timeout and output-token limit on inference. Log duration and status, but never prompts containing sensitive raw data or any credentials. The endpoint is chargeable while active, so deployment notes must include how to stop/delete it after the demo.

## Security and privacy

Never expose Home Assistant port 8123 directly to the public internet merely for this app. The simplest safe demo is to run Climate Detective on the home network: it reads Home Assistant locally and makes only an outbound request containing derived events to Nebius. The frontend talks to Climate Detective, not Home Assistant or Nebius.

If Climate Detective must run in the cloud, connect it to the home through an authenticated encrypted tunnel or a narrow read-only gateway. Use TLS, a dedicated non-admin Home Assistant user/token where supported, a fixed entity allowlist, rate limiting, and token rotation. A Home Assistant bearer token may grant access beyond these three sensors; application-side filtering alone is not an authorization boundary.

Secrets belong in environment variables or the deployment secret store. Commit an `.env.example` containing names only. Never return secrets in API errors, log authorization headers, put credentials in JavaScript, or commit real household telemetry. Use synthetic or anonymized fixtures.

If the API is public, protect it with at least a demo access key and rate limiting because every request can reach private data and trigger paid inference. Restrict allowed origins if frontend and API cannot share an origin.

## Implementation conventions

- Use type hints and small dataclasses or Pydantic models at network/domain boundaries.
- Prefer `httpx` for both external HTTP integrations.
- Use the standard `zoneinfo` module for timezone handling.
- Keep dependencies minimal and pinned through the project's chosen dependency file.
- Use structured logging; include request IDs and durations, not sensor payloads or tokens.
- Do not silently catch broad exceptions. Translate known integration errors into safe, actionable API responses.
- Keep UI JavaScript dependency-free. The page needs a period selector, submit button, loading state, error state, summary, and a compact facts list. Ensure labels, keyboard navigation, and readable contrast.

## Verification

At minimum, tests must cover:

- today/yesterday/last-seven-day boundaries in the configured timezone;
- a daylight-saving boundary;
- unsorted, unavailable, sparse, and empty Home Assistant samples;
- temperature/humidity rise/drop extrema segmentation, threshold hysteresis, and calm-series fallback;
- W-to-kWh integration or cumulative-kWh delta, whichever the configured fixture uses;
- LLM success, timeout, malformed response, and deterministic fallback;
- the summary endpoint with Home Assistant and LLM calls mocked.
- current-state normalization, numeric/raw values, and per-sensor error isolation.

Before handing off changes, run the formatter, linter, and test suite documented in `README.md`. Never make tests depend on a real home or a live Nebius endpoint.

## Deliberate non-goals for the PoC

Do not add a database, background scheduler, WebSockets, multi-home tenancy, authentication accounts, dashboards, forecasting, autonomous Home Assistant control, or raw telemetry uploads unless the user explicitly expands the scope. In particular, Climate Detective is read-only: it must not call Home Assistant service/action endpoints.

## Primary references

- Home Assistant REST API: https://developers.home-assistant.io/docs/api/rest/
- Nebius Serverless AI overview: https://docs.nebius.com/serverless/overview
- Nebius vLLM endpoint tutorial: https://docs.nebius.com/serverless/tutorials/deploy-model
