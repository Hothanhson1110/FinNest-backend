from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from app.providers.dnse import DNSEMarketDataError, DNSEMarketDataProvider

APP_MODE = os.getenv("FINNEST_MARKET_MODE", "mock").strip().lower()
ALLOWED_SYMBOL = re.compile(r"^[A-Z0-9]{2,12}$")
dnse_provider = DNSEMarketDataProvider()

app = FastAPI(
    title="FinNest Market Backend",
    version="0.8.0",
    description="Read-only market-data proxy for FinNest.",
)


def _symbols(raw: str) -> list[str]:
    items = [x.strip().upper() for x in raw.split(",") if x.strip()]
    if not items or len(items) > 10 or any(not ALLOWED_SYMBOL.fullmatch(x) for x in items):
        raise HTTPException(status_code=400, detail="symbols must contain 1-10 valid symbols")
    return list(dict.fromkeys(items))


def _mock_quote(symbol: str) -> dict[str, Any]:
    fixtures = {
        "FPT": (54000.0, 500.0, 0.93),
        "HPG": (27100.0, -200.0, -0.73),
        "VCB": (92300.0, 300.0, 0.33),
    }
    price, change, percent = fixtures.get(symbol, (10000.0, 0.0, 0.0))
    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "changePercent": percent,
        "currency": "VND",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "mock",
    }


def _mock_candles(symbol: str, limit: int) -> list[dict[str, Any]]:
    closes = [
        48.2, 48.7, 48.4, 49.1, 49.6, 49.2, 49.8, 50.1, 49.7, 50.4,
        50.8, 50.2, 50.6, 51.1, 50.9, 51.5, 51.2, 51.8, 52.1, 51.6,
        52.4, 52.8, 52.2, 52.7, 53.1, 52.9, 53.4, 53.0, 53.7, 54.0,
    ]
    rows = []
    selected = closes[-limit:]
    for i, close in enumerate(selected):
        prev = selected[i - 1] if i > 0 else close - 0.3
        open_price = prev + (0.12 if i % 2 == 0 else -0.10)
        rows.append({
            "symbol": symbol,
            "timestamp": 1_760_000_000_000 + i * 86_400_000,
            "open": round(open_price, 3),
            "high": round(max(open_price, close) + 0.25, 3),
            "low": round(min(open_price, close) - 0.20, 3),
            "close": close,
            "volume": 1000 + i * 125,
            "source": "mock",
        })
    return rows


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "mode": APP_MODE,
        "service": "finnest-market-backend",
    }


@app.get("/api/v1/market/quotes")
def quotes(symbols: str = Query(..., min_length=2, max_length=120)) -> dict[str, Any]:
    requested = _symbols(symbols)
    if APP_MODE != "mock":
        raise HTTPException(
            status_code=503,
            detail="Production quotes are unavailable until a verified last-traded-price source is implemented.",
        )
    return {
        "data": [_mock_quote(symbol) for symbol in requested],
        "meta": {"source": "mock", "isLive": False},
    }


@app.get("/api/v1/market/ohlc")
def ohlc(
    symbol: str = Query(..., min_length=2, max_length=12),
    interval: str = Query("1D", pattern="^(1|5|15|30|60|1D|1W)$"),
    limit: int = Query(30, ge=1, le=250),
    from_ts: int | None = Query(None, alias="from", gt=0),
    to_ts: int | None = Query(None, alias="to", gt=0),
) -> dict[str, Any]:
    requested = _symbols(symbol)
    if len(requested) != 1:
        raise HTTPException(status_code=400, detail="provide one symbol")

    if APP_MODE == "mock":
        return {
            "data": _mock_candles(requested[0], limit),
            "meta": {
                "symbol": requested[0],
                "interval": interval,
                "source": "mock",
                "isLive": False,
            },
        }

    if APP_MODE not in {"dnse", "dnse_ohlc"}:
        raise HTTPException(status_code=503, detail="Unsupported market-data mode.")

    now = datetime.now(timezone.utc)
    if from_ts is None or to_ts is None:
        if interval in {"1", "5", "15", "30", "60"}:
            start = now - timedelta(days=2)
        elif interval == "1W":
            start = now - timedelta(days=365 * 3)
        else:
            start = now - timedelta(days=90)
        from_ts = int(start.timestamp())
        to_ts = int(now.timestamp())

    if to_ts <= from_ts:
        raise HTTPException(status_code=400, detail="'to' must be later than 'from'.")
    if to_ts - from_ts > 366 * 24 * 60 * 60:
        raise HTTPException(status_code=400, detail="OHLC range cannot exceed 366 days.")

    try:
        result = dnse_provider.get_ohlc(
            symbol=requested[0],
            interval=interval,
            start=from_ts,
            end=to_ts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DNSEMarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DNSE market-data request failed.") from exc

    result["data"] = result["data"][-limit:]
    result["meta"]["interval"] = interval
    return result


@app.exception_handler(Exception)
async def safe_unexpected_error(_request, _exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
