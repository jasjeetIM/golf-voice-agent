# Golf Voice Agent (Python)

Python port of the `golf-voice-agent` services:

- `backend`: tee time inventory + reservations + tools API
- `voice_gateway`: Twilio media stream + OpenAI Realtime agent

## Quick start

1. Install dependencies (example using uv or pip):

```bash
pip install -e /Users/dhalijs1/Documents/voice_agent/openai-agents-python
pip install -e ./python
export PYTHONPATH=./python
```

2. Backend

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8081
```

3. Voice gateway

```bash
uvicorn voice_gateway.app.main:app --host 0.0.0.0 --port 8080
```

## Environment

- `OPENAI_API_KEY`
- `BACKEND_API_KEY`
- `DB_CONNECTION_STRING`
- `PUBLIC_HOST`, `PUBLIC_PROTOCOL`, `VOICE_GATEWAY_PORT`, `BACKEND_PORT`
