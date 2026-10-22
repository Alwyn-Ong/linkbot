import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api-open.data.gov.sg/v2/real-time/api"
FORECAST_URL = f"{BASE_URL}/two-hr-forecast"
PSI_URL = f"{BASE_URL}/psi"
CACHE_TTL = 15 * 60

_cache: dict = {}


def _cached(key: str, fetch):
    entry = _cache.get(key)
    if entry and time.monotonic() - entry["at"] < CACHE_TTL:
        return entry["data"]
    try:
        data = fetch()
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        logger.warning("%s fetch failed: %s", key, e)
        # Serve a stale reading over none: slightly old beats no re-ranking.
        return entry["data"] if entry else None
    _cache[key] = {"at": time.monotonic(), "data": data}
    return data


def _fetch_forecast() -> dict:
    resp = requests.get(FORECAST_URL, timeout=10)
    resp.raise_for_status()
    item = resp.json()["data"]["items"][0]
    return {
        "valid_period": item["valid_period"]["text"],
        "areas": {f["area"]: f["forecast"] for f in item["forecasts"]},
    }


def _fetch_psi() -> dict:
    resp = requests.get(PSI_URL, timeout=10)
    resp.raise_for_status()
    readings = resp.json()["data"]["items"][0]["readings"]
    return {
        "psi": readings["psi_twenty_four_hourly"],
        "pm25": readings["pm25_twenty_four_hourly"],
    }


def get_conditions() -> str | None:
    """Prompt-ready text of the forecast per area and PSI per region, or None if both are down."""
    forecast = _cached("forecast", _fetch_forecast)
    psi = _cached("psi", _fetch_psi)
    lines = []
    if forecast:
        lines.append(f"2-hour forecast ({forecast['valid_period']}), by area:")
        lines += [f"- {area}: {text}" for area, text in forecast["areas"].items()]
    if psi:
        lines.append("24-hour PSI (0-50 good, 51-100 moderate, 101+ unhealthy) and PM2.5, by region:")
        lines += [f"- {region}: PSI {value}, PM2.5 {psi['pm25'][region]}" for region, value in psi["psi"].items()]
    return "\n".join(lines) or None
