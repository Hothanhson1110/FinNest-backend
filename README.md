# FinNest Termux Market Backend v0.7.0

Read-only FastAPI backend for local contract testing from Android/Termux.

## Security boundaries

- Binds to `127.0.0.1` only by default.
- Default `FINNEST_MARKET_MODE=mock`; responses are explicitly marked `source=mock`, `isLive=false`.
- Does not place trades or expose account/order endpoints.
- Does not implement DNSE authentication yet. Do not set mode to `dnse` expecting real data.
- Never put DNSE API Key/Secret in the Android APK, GitHub, screenshots, or logs.
- Do not expose this local server to the public internet without HTTPS, access control, rate limits, and a reviewed DNSE adapter.

## Install in Termux

```sh
pkg update
pkg install python
mkdir -p ~/FinNest-backend
# Extract this ZIP into ~/FinNest-backend, then:
cd ~/FinNest-backend
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Keep the server running in this Termux session.

## Test in a second Termux session

```sh
curl -sS http://127.0.0.1:8787/health
curl -sS 'http://127.0.0.1:8787/api/v1/market/quotes?symbols=FPT,HPG,VCB'
curl -sS 'http://127.0.0.1:8787/api/v1/market/ohlc?symbol=FPT&interval=1D&limit=30'
```

Expected:
- `/health` returns `status=ok`.
- quote response contains `meta.source=mock` and `meta.isLive=false`.
- OHLC response contains `open`, `high`, `low`, `close`, `volume`.
- These are test fixtures, NOT DNSE prices.

Interactive docs (local only): `http://127.0.0.1:8787/docs`

## App integration note

FinNest Android validates `MARKET_API_BASE_URL` as HTTPS and disables cleartext traffic. Therefore this `http://127.0.0.1` endpoint is for Termux/curl testing only and will not work in the current APK. To connect the app, use a trusted HTTPS endpoint/tunnel with authentication, or create a debug-only local HTTP build that cannot be released. Do not disable TLS for release builds.

## DNSE live data is a separate next step

DNSE publishes official market-data APIs for historical OHLC and quotes. The official Python SDK handles request signing and supports market data; verify the current method signature and response schema against DNSE docs before enabling a real adapter. Keep credentials only in Termux environment variables for a private experiment, and rotate them if they are ever exposed. No DNSE credentials are needed for the mock-mode test.
