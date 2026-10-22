import os
import sys
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import weather

FORECAST = {"data": {"items": [{
    "valid_period": {"text": "10.00 pm to Midnight"},
    "forecasts": [
        {"area": "City", "forecast": "Cloudy"},
        {"area": "Bedok", "forecast": "Light Rain"},
    ],
}]}}

PSI = {"data": {"items": [{"readings": {
    "psi_twenty_four_hourly": {"north": 70, "west": 87},
    "pm25_twenty_four_hourly": {"north": 29, "west": 44},
}}]}}


def _resp(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _get(url, **kwargs):
    return _resp(FORECAST if url == weather.FORECAST_URL else PSI)


def setup_function():
    weather._cache.clear()


def test_includes_forecast_and_psi():
    with patch("weather.requests.get", side_effect=_get):
        text = weather.get_conditions()
    assert "- Bedok: Light Rain" in text
    assert "- west: PSI 87, PM2.5 44" in text


def test_cache_hit_skips_second_request():
    with patch("weather.requests.get", side_effect=_get) as get:
        weather.get_conditions()
        weather.get_conditions()
    assert get.call_count == 2  # one per endpoint, not per call


def test_api_down_returns_none():
    with patch("weather.requests.get", side_effect=requests.ConnectionError):
        assert weather.get_conditions() is None


def test_one_endpoint_down_still_returns_the_other():
    def get(url, **kwargs):
        if url == weather.PSI_URL:
            raise requests.ConnectionError
        return _get(url)

    with patch("weather.requests.get", side_effect=get):
        text = weather.get_conditions()
    assert "Bedok" in text and "PSI" not in text


def test_api_down_serves_stale_cache():
    with patch("weather.requests.get", side_effect=_get):
        weather.get_conditions()
    for entry in weather._cache.values():
        entry["at"] = 0.0
    with patch("weather.requests.get", side_effect=requests.ConnectionError):
        assert "Bedok" in weather.get_conditions()


def test_malformed_response_returns_none():
    with patch("weather.requests.get", return_value=_resp({"data": {}})):
        assert weather.get_conditions() is None
