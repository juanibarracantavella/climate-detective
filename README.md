# Climate Detective

A small FastAPI and vanilla JavaScript proof of concept that turns Home Assistant temperature, humidity, and power history into deterministic facts and a plain-language summary.

## How it works

The backend fetches an allowlisted set of Home Assistant entities, groups noisy readings into 15-minute bins, calculates statistics and notable changes, and sends only those derived facts to an OpenAI-compatible LLM on Nebius Serverless AI. If the model is unavailable, the API returns a local fallback summary instead.

The browser never receives Home Assistant or Nebius credentials.

## Run locally

Prerequisites: Python 3.12+ and a Home Assistant long-lived access token.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env` with your entity IDs, home timezone, tokens, and endpoint. Load it and start the app:

```bash
make run
```

Open http://127.0.0.1:8000. API documentation is available at http://127.0.0.1:8000/docs.

For the safest demo, run this application on the same private network as Home Assistant and use its local URL. Do not port-forward Home Assistant's port 8123 just for this project.

## Nebius model endpoint

Climate Detective supports two named OpenAI-compatible Nebius endpoints. Select one profile and
configure both profiles independently:

```dotenv
NEBIUS_PROFILE=strong

NEBIUS_FAST_BASE_URL=http://<fast-endpoint-address>/v1
NEBIUS_FAST_API_KEY=<fast-endpoint-token>
NEBIUS_FAST_MODEL=Qwen/Qwen3-0.6B

NEBIUS_STRONG_BASE_URL=http://<strong-endpoint-address>/v1
NEBIUS_STRONG_API_KEY=<strong-endpoint-token>
NEBIUS_STRONG_MODEL=Qwen/Qwen2.5-7B-Instruct
```

Set `NEBIUS_PROFILE=fast` to switch back without moving credentials. The app automatically appends
`/v1` when it is omitted. If the selected profile has no API key or model, the app deliberately uses
its deterministic fallback summary. Stop or delete Nebius endpoints when the demo is over to avoid
continued compute charges.

The port exposed by the Nebius endpoint must match the port passed to vLLM. For example, a public
URL beginning with `https://port8080-...` requires vLLM to listen on port 8080:

```bash
python3 -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 \
  --port 8080 \
  --max-model-len 32768
```

If vLLM instead listens on port 8000, expose port 8000 and use the resulting `port8000-...` URL.
A mismatch commonly appears as `502 Bad Gateway` because the endpoint cannot reach vLLM.

## Checks

```bash
ruff check .
ruff format --check .
pytest
```

All tests use synthetic sensor readings and mocked integrations; they do not contact a real home or model.

## API

```http
GET /api/summary?period=today
GET /api/summary?period=yesterday
GET /api/summary?period=last_7_days
GET /api/summary-prompt?period=today
GET /api/home-sensors
GET /api/health
```

`GET /api/home-sensors` reads the seven configured current-state entities directly from Home Assistant. Each item contains the normalized numeric `value`, original `raw_state`, unit, friendly name, timestamps, and a per-sensor `error`. A failed entity does not prevent the remaining readings from being returned.

`GET /api/summary-prompt` returns the exact OpenAI-compatible JSON request body that the summarizer would send for the selected period, without calling Nebius. It contains only the locally derived facts and no credentials or raw sensor samples.

See [AGENTS.md](AGENTS.md) for design constraints, security guidance, and the intended PoC scope.

For a presentation-ready walkthrough, use [hackathon-demo-guide.md](hackathon-demo-guide.md).
