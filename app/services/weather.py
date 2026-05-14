"""Weather + reverse-geocoding context for captures.

Sources (both free, no API key required):
  - Weather: Open-Meteo  (https://open-meteo.com)
  - Reverse geocode: OpenStreetMap Nominatim
    Open-Meteo's geocoding API is forward-only (name → coords); for reverse we
    fall back to Nominatim, which is the standard free option for personal use.

Results are cached for 15 minutes per ~1 km grid cell.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx


CACHE_TTL_SECONDS = 15 * 60

# (rounded_lat, rounded_lon) -> (epoch_when_fetched, context_dict)
_cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}


# WMO weather code → (condition text, day emoji, night emoji)
# https://open-meteo.com/en/docs (weather_code section)
_CODE_TABLE: dict[int, tuple[str, str, str]] = {
    0:  ("Clear sky",                "☀️", "🌙"),
    1:  ("Mainly clear",             "🌤️", "🌙"),
    2:  ("Partly cloudy",            "⛅", "☁️"),
    3:  ("Overcast",                 "☁️", "☁️"),
    45: ("Fog",                      "🌫️", "🌫️"),
    48: ("Rime fog",                 "🌫️", "🌫️"),
    51: ("Light drizzle",            "🌦️", "🌧️"),
    53: ("Moderate drizzle",         "🌦️", "🌧️"),
    55: ("Dense drizzle",            "🌦️", "🌧️"),
    56: ("Light freezing drizzle",   "🌧️", "🌧️"),
    57: ("Dense freezing drizzle",   "🌧️", "🌧️"),
    61: ("Light rain",               "🌧️", "🌧️"),
    63: ("Moderate rain",            "🌧️", "🌧️"),
    65: ("Heavy rain",               "🌧️", "🌧️"),
    66: ("Light freezing rain",      "🌧️", "🌧️"),
    67: ("Heavy freezing rain",      "🌧️", "🌧️"),
    71: ("Light snow",               "🌨️", "🌨️"),
    73: ("Moderate snow",            "🌨️", "🌨️"),
    75: ("Heavy snow",               "❄️", "❄️"),
    77: ("Snow grains",              "🌨️", "🌨️"),
    80: ("Light rain showers",       "🌦️", "🌧️"),
    81: ("Moderate rain showers",    "🌦️", "🌧️"),
    82: ("Violent rain showers",     "⛈️", "⛈️"),
    85: ("Light snow showers",       "🌨️", "🌨️"),
    86: ("Heavy snow showers",       "🌨️", "🌨️"),
    95: ("Thunderstorm",             "⛈️", "⛈️"),
    96: ("Thunderstorm with hail",   "⛈️", "⛈️"),
    99: ("Thunderstorm w/ heavy hail","⛈️", "⛈️"),
}

NOMINATIM_HEADERS = {
    "User-Agent": "SecondBrain/1.0 (personal note capture)",
    "Accept": "application/json",
    "Accept-Language": "en",
}


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    # Round to 2 decimals → ~1 km cells; nearby captures share the cache entry.
    return (round(lat, 2), round(lon, 2))


def get_context(lat: float, lon: float) -> Optional[dict[str, Any]]:
    """Fetch (or return cached) weather + location for these coordinates.

    Returns a dict with whichever of `temp_c`, `condition`, `weather_emoji`,
    and `location` could be obtained, plus the original `lat`/`lon`.
    Returns None only if BOTH weather and reverse-geocode fail entirely.
    """
    key = _cache_key(lat, lon)
    now = time.time()

    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    ctx: dict[str, Any] = {"lat": lat, "lon": lon}
    weather_ok = _fetch_weather(lat, lon, ctx)
    location_ok = _fetch_location(lat, lon, ctx)

    if not weather_ok and not location_ok:
        return None

    _cache[key] = (now, ctx)
    return ctx


def _fetch_weather(lat: float, lon: float, ctx: dict[str, Any]) -> bool:
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code,is_day",
                    "timezone": "auto",
                },
            )
            r.raise_for_status()
            data = r.json().get("current") or {}
    except Exception:
        return False

    temp = data.get("temperature_2m")
    if isinstance(temp, (int, float)):
        ctx["temp_c"] = round(float(temp), 1)

    code = data.get("weather_code")
    is_day = bool(data.get("is_day", 1))
    if isinstance(code, int) and code in _CODE_TABLE:
        cond, day_emoji, night_emoji = _CODE_TABLE[code]
        ctx["condition"] = cond
        ctx["weather_emoji"] = day_emoji if is_day else night_emoji

    return any(k in ctx for k in ("temp_c", "condition"))


def _fetch_location(lat: float, lon: float, ctx: dict[str, Any]) -> bool:
    try:
        with httpx.Client(timeout=8.0, headers=NOMINATIM_HEADERS) as client:
            r = client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "format": "json",
                    "lat": lat,
                    "lon": lon,
                    "zoom": 12,           # city/town level
                    "addressdetails": 1,
                },
            )
            r.raise_for_status()
            geo = r.json()
    except Exception:
        return False

    address = geo.get("address") or {}
    location = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("hamlet")
        or address.get("suburb")
        or address.get("municipality")
        or address.get("county")
        or address.get("state")
    )
    if location:
        ctx["location"] = location
        return True
    return False


def format_header_suffix(ctx: Optional[dict[str, Any]]) -> str:
    """Format the bit after `## HH:MM` in daily-note headers.

    Examples:
      ☀️ 22°C, partly cloudy · Coburg
      🌙 -3°C, clear sky
      Coburg
    """
    if not ctx:
        return ""

    parts: list[str] = []

    emoji = ctx.get("weather_emoji")
    temp = ctx.get("temp_c")
    cond = ctx.get("condition")

    weather_bits: list[str] = []
    if emoji:
        weather_bits.append(emoji)
    if temp is not None:
        weather_bits.append(f"{_fmt_temp(temp)}°C")
    if cond:
        # Combine temp and condition with a comma if both present
        if temp is not None:
            weather_bits[-1] = f"{weather_bits[-1]}, {cond.lower()}"
        else:
            weather_bits.append(cond.lower())
    if weather_bits:
        parts.append(" ".join(weather_bits))

    location = ctx.get("location")
    if location:
        parts.append(location)

    return " · ".join(parts)


def _fmt_temp(t: float) -> str:
    # 22.0 → "22", 22.4 → "22.4", -5.0 → "-5"
    if float(t).is_integer():
        return str(int(t))
    return f"{t:.1f}"
