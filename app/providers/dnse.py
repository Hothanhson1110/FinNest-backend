from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from dnse import DNSEClient


_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,12}$")

_INTERVALS = {
    "1": "1",
    "5": "5",
    "15": "15",
    "30": "30",
    "60": "1H",
    "1D": "1D",
    "1W": "1W",
}


class DNSEMarketDataError(RuntimeError):
    """Raised when DNSE data cannot be fetched or validated."""


class DNSEMarketDataProvider:
    """Read-only adapter for DNSE production market data."""

    def __init__(self) -> None:
        self._api_key = os.getenv("DNSE_PROD_API_KEY", "").strip()
        self._api_secret = os.getenv("DNSE_PROD_API_SECRET", "").strip()
        self._base_url = "https://openapi.dnse.com.vn"

    def _client(self) -> DNSEClient:
        if not self._api_key or not self._api_secret:
            raise DNSEMarketDataError(
                "DNSE production credentials are not configured"
            )

        return DNSEClient(
            api_key=self._api_key,
            api_secret=self._api_secret,
            base_url=self._base_url,
        )

    @staticmethod
    def _decode_response(status: int, body: str) -> dict[str, Any]:
        if status != 200:
            raise DNSEMarketDataError(
                f"DNSE returned HTTP {status}"
            )

        try:
            result = json.loads(body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DNSEMarketDataError(
                "DNSE returned invalid JSON"
            ) from exc

        if not isinstance(result, dict):
            raise DNSEMarketDataError("Unexpected DNSE response format")

        return result

    def get_ohlc(
        self,
        symbol: str,
        interval: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()

        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError("Invalid stock symbol")
        if interval not in _INTERVALS:
            raise ValueError("Unsupported interval")
        if start <= 0 or end <= start:
            raise ValueError("Invalid time range")

        status, body = self._client().get_ohlc(
            bar_type="STOCK",
            query={
                "symbol": symbol,
                "resolution": _INTERVALS[interval],
                "from": start,
                "to": end,
            },
        )
        result = self._decode_response(status, body)

        fields = ("t", "o", "h", "l", "c", "v")
        arrays = [result.get(field) for field in fields]

        # DNSE can return null arrays when no candles are available.
        if all(value is None for value in arrays):
            candles: list[dict[str, Any]] = []
        elif not all(isinstance(value, list) for value in arrays):
            raise DNSEMarketDataError("Incomplete OHLC arrays")
        else:
            lengths = {len(value) for value in arrays}
            if len(lengths) != 1:
                raise DNSEMarketDataError("OHLC arrays have different lengths")

            timestamps, opens, highs, lows, closes, volumes = arrays
            candles = []

            for timestamp, open_, high, low, close, volume in zip(
                timestamps, opens, highs, lows, closes, volumes
            ):
                values = (open_, high, low, close, volume)
                if timestamp is None or any(v is None for v in values):
                    continue

                try:
                    timestamp_ms = int(timestamp) * 1000
                    # Normalize DNSE stock prices from thousand VND to VND
                    open_ = round(float(open_) * 1000)
                    high = round(float(high) * 1000)
                    low = round(float(low) * 1000)
                    close = round(float(close) * 1000)
                    volume = int(volume)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise DNSEMarketDataError(
                        "Invalid value in OHLC data"
                    ) from exc

                if (
                    min(open_, high, low, close) <= 0
                    or high < max(open_, close, low)
                    or low > min(open_, close, high)
                    or volume < 0
                ):
                    raise DNSEMarketDataError("Invalid OHLC candle")

                candles.append({
                    "symbol": symbol,
                    "timestamp": timestamp_ms,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "source": "dnse",
                })

            candles.sort(key=lambda candle: candle["timestamp"])

        return {
            "data": candles,
            "meta": {
                "symbol": symbol,
                "interval": interval,
                "source": "dnse",
                "isLive": False,
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "nextTime": result.get("nextTime"),
            },
        }
