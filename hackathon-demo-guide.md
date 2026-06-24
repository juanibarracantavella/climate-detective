# Climate Detective hackathon demo guide

This guide is a short, repeatable path for demonstrating that Climate Detective reads real Home Assistant data, analyzes historical readings, and produces a human-readable summary.

## Before the demo

From the project directory, confirm that `.env` contains the real Home Assistant token and the correct home timezone. Do not display or share this file during the presentation.

At minimum, these values must be configured:

```dotenv
HA_BASE_URL=https://home.cosasdejuan.es
HA_TOKEN=<your long-lived access token>
HOME_TIMEZONE=<your IANA timezone, for example Europe/Madrid>
```

If a Nebius endpoint is ready, also configure `NEBIUS_BASE_URL`, `NEBIUS_API_KEY`, and `NEBIUS_MODEL`. Otherwise, Climate Detective will use its deterministic local summary, which is a valid fallback for the demo.

Install and verify the application once before presenting:

```bash
make setup
make check
```

Expected test result:

```text
16 passed
```

## 1. Start Climate Detective

Run:

```bash
make run
```

Keep this terminal visible enough to notice request logs, but make sure it does not show `.env` contents or authorization headers.

The application is now available at:

- Frontend: http://127.0.0.1:8000/
- API documentation: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health

## 2. Optional: prove Home Assistant works directly

This section is useful immediately before the presentation or if someone asks whether the readings are real. Open a second terminal and load the environment without printing it:

```bash
set -a
source .env
set +a
```

### Check the Home Assistant API

```bash
curl -sS \
  -H "Authorization: Bearer ${HA_TOKEN}" \
  -H "Content-Type: application/json" \
  "${HA_BASE_URL}/api/" | jq
```

Expected response:

```json
{
  "message": "API running."
}
```

### Fetch one current sensor directly

```bash
curl -sS \
  -H "Authorization: Bearer ${HA_TOKEN}" \
  -H "Content-Type: application/json" \
  "${HA_BASE_URL}/api/states/sensor.average_indoor_temperature" \
  | jq '{entity_id, state, unit: .attributes.unit_of_measurement, friendly_name: .attributes.friendly_name, last_updated}'
```

This demonstrates that `/api/states/{entity_id}` returns the latest value only.

### Fetch a historical series directly

Set an interval appropriate for the demo date. The example below uses UTC; change the timestamps to match the home timezone and desired date.

```bash
START='2026-06-24T00:00:00+00:00'
END='2026-06-24T23:59:59+00:00'

curl -sS --get \
  -H "Authorization: Bearer ${HA_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-urlencode "end_time=${END}" \
  --data-urlencode "filter_entity_id=sensor.average_indoor_temperature,sensor.average_indoor_humidity,sensor.total_power_meter_power" \
  --data-urlencode "minimal_response=" \
  --data-urlencode "no_attributes=" \
  "${HA_BASE_URL}/api/history/period/${START}" \
  | jq 'map({entity: .[0].entity_id, samples: length, first: .[0], last: .[-1]})'
```

This is the historical API used by the summary pipeline. Home Assistant returns one array per entity.

## 3. Demonstrate the Climate Detective API

These requests go to the local backend. The browser never receives the Home Assistant token.

### Health check

```bash
curl -sS http://127.0.0.1:8000/api/health | jq
```

Expected response:

```json
{
  "status": "ok"
}
```

### Show all current sensors

```bash
curl -sS http://127.0.0.1:8000/api/home-sensors | jq
```

This returns the seven allowlisted sensors. Each successful item includes:

- `entity_id`
- normalized numeric `value`
- original `raw_state`
- `unit` and `friendly_name`
- Home Assistant timestamps
- `error`, which is `null` on success

For a cleaner presentation, display only the names, values, units, and errors:

```bash
curl -sS http://127.0.0.1:8000/api/home-sensors \
  | jq '{fetched_at, sensors: [.sensors[] | {friendly_name, value, unit, error}]}'
```

Confirm that no sensor failed:

```bash
curl -sS http://127.0.0.1:8000/api/home-sensors \
  | jq '.sensors[] | select(.error != null)'
```

No output means all seven sensors were fetched successfully.

### Generate a historical summary

Today:

```bash
curl -sS "http://127.0.0.1:8000/api/summary?period=today" | jq
```

Yesterday:

```bash
curl -sS "http://127.0.0.1:8000/api/summary?period=yesterday" | jq
```

Last seven days:

```bash
curl -sS "http://127.0.0.1:8000/api/summary?period=last_7_days" | jq
```

Point out these parts of the response:

- `summary`: natural-language explanation
- `statistics`: calculated averages, coverage, and estimated energy use
- `events`: detected temperature/humidity changes and power spikes
- `warnings`: missing-data or local-fallback notes
- `period`: exact timezone-aware interval analyzed

The statistics and events are calculated locally. The LLM is used only to translate those facts into friendlier wording.

## 4. Demonstrate the frontend

Open http://127.0.0.1:8000/ in a browser.

Suggested presentation flow:

1. Explain that the browser talks only to the local Climate Detective backend.
2. Select **Today** and click **Investigate**.
3. Read the generated summary.
4. Show the evidence cards containing temperature, humidity, energy, and data coverage.
5. Show any detected notable changes.
6. Repeat with **Yesterday** or **Last 7 days** to demonstrate historical queries.

If the first request takes a little longer, explain that it fetches Home Assistant history and may call the model. Repeated requests within the short cache window should be faster.

## 5. Optional: prove Nebius inference is active

Only do this if the Nebius environment variables are configured. Do not show the token.

```bash
curl -sS \
  -H "Authorization: Bearer ${NEBIUS_API_KEY}" \
  "${NEBIUS_BASE_URL}/models" \
  | jq '.data[] | {id}'
```

Then call the Climate Detective summary endpoint and inspect `warnings`:

```bash
curl -sS "http://127.0.0.1:8000/api/summary?period=today" \
  | jq '{summary, warnings}'
```

If the warnings contain `Nebius is not configured` or `Nebius summary failed`, the displayed text is the deterministic local fallback. This does not affect the calculated statistics or events.

## Three-minute talk track

1. **Problem:** Home Assistant stores useful telemetry, but raw time series are tedious to interpret.
2. **Live data:** Show `/api/home-sensors` returning the seven real current readings.
3. **Analysis:** Explain that Climate Detective requests historical temperature, humidity, and power data, bins it into 15-minute intervals, calculates statistics, integrates power into kWh, and splits temperature and humidity into rise/drop periods. Significant swings use local turning points; calmer periods are divided around the overall low and high so their daily shape remains visible.
4. **AI role:** Explain that only derived facts are sent to the LLM; the LLM does not calculate numbers or receive credentials.
5. **Result:** Use the frontend to generate a summary for today and another period.
6. **Safety:** The token remains in the backend `.env`, entities are allowlisted, and partial sensor failures do not break the entire snapshot.

## Quick troubleshooting

### `make run` reports that `.env` is missing

```bash
cp .env.example .env
```

Then add the real `HA_TOKEN` and restart.

### Home Assistant says the token is missing or rejected

- Confirm `HA_TOKEN` is populated in `.env` with no surrounding placeholder text.
- Restart `make run` after editing `.env`.
- Create a new Long-Lived Access Token if the old one was revoked.

### A sensor reports HTTP 404

Verify its exact entity ID in Home Assistant Developer Tools → States. One failed sensor is returned with an `error`; the other sensors should still work.

### Current values work but a summary has little or no history

The current endpoint and history endpoint are different. Confirm that Home Assistant Recorder retains those entities and that the selected period contains readings. Check the direct history command above.

### Summary mentions a local fallback

Configure the three Nebius variables and restart the backend. Until then, the deterministic fallback is expected.

### Port 8000 is already in use

Find and stop the old development server, or temporarily run:

```bash
.venv/bin/uvicorn app.main:app --reload --env-file .env --port 8001
```

Then use `http://127.0.0.1:8001` for the frontend and API examples.

## After the demo

- Stop the local server with `Ctrl+C`.
- Stop or delete the Nebius Serverless AI endpoint if it should not continue consuming paid compute.
- Never commit `.env`, access tokens, copied API responses containing private household data, or screenshots that reveal credentials.
