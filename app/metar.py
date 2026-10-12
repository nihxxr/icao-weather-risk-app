"""Fetch and normalise METAR observations.

Two sources:
- AVWX (https://avwx.rest) when AVWX_TOKEN is set.
- NOAA's Aviation Weather Center API (https://aviationweather.gov) otherwise.
  It needs no key, so the app runs out of the box.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import requests

SM_TO_KM = 1.609344
ICAO_RE = re.compile(r"^[A-Z0-9]{4}$")
TIMEOUT = 10


class MetarError(Exception):
    """A lookup failed in a way the person can act on."""


@dataclass
class Observation:
    station: str
    raw: str = ""
    name: str = ""
    observed: str = ""
    wind_kt: float = 0.0
    wind_dir: str = ""
    gust_kt: float | None = None
    vis_km: float = 10.0
    temp_c: float | None = None
    dew_c: float | None = None
    ceiling_ft: int | None = None
    clouds: list = field(default_factory=list)
    source: str = ""

    def to_dict(self):
        return asdict(self)


def normalise_icao(code: str) -> str:
    code = (code or "").strip().upper()
    if not ICAO_RE.match(code):
        raise MetarError("ICAO codes are four letters or digits, like VOBL or KJFK.")
    return code


def ceiling_from(layers: list[tuple[str, int | None]]) -> int | None:
    """Lowest broken, overcast or vertical visibility layer, in feet."""
    bases = [b for cover, b in layers if cover in ("BKN", "OVC", "VV", "OVX") and b is not None]
    return min(bases) if bases else None


def _num(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.match(r"^\s*(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else default


# --- Aviation Weather Center -------------------------------------------------

def _from_awc(icao: str) -> Observation:
    url = "https://aviationweather.gov/api/data/metar"
    resp = requests.get(url, params={"ids": icao, "format": "json"}, timeout=TIMEOUT,
                        headers={"User-Agent": "icao-weather-risk-app"})
    if resp.status_code == 204 or not resp.content:
        raise MetarError(f"No current METAR for {icao}. Check the code, or the station may not report.")
    if resp.status_code != 200:
        raise MetarError(f"The weather service returned an error ({resp.status_code}). Try again in a minute.")
    data = resp.json()
    if not data:
        raise MetarError(f"No current METAR for {icao}. Check the code, or the station may not report.")
    m = data[0]

    layers = [(c.get("cover", ""), int(c["base"]) if c.get("base") is not None else None)
              for c in (m.get("clouds") or [])]
    vis_sm = _num(m.get("visib"), 10.0)
    wdir = m.get("wdir")
    return Observation(
        station=icao,
        raw=m.get("rawOb", ""),
        name=(m.get("name") or "").split(",")[0].strip(),
        observed=m.get("reportTime") or "",
        wind_kt=_num(m.get("wspd"), 0.0),
        wind_dir="VRB" if wdir == "VRB" else (f"{int(wdir):03d}" if isinstance(wdir, (int, float)) else ""),
        gust_kt=_num(m.get("wgst")),
        vis_km=round(vis_sm * SM_TO_KM, 1),
        temp_c=_num(m.get("temp")),
        dew_c=_num(m.get("dewp")),
        ceiling_ft=ceiling_from(layers),
        clouds=[{"cover": c, "base_ft": b} for c, b in layers],
        source="NOAA Aviation Weather Center",
    )


# --- AVWX ----------------------------------------------------------------------

def _from_avwx(icao: str, token: str) -> Observation:
    url = f"https://avwx.rest/api/metar/{icao}"
    resp = requests.get(url, params={"options": "info", "format": "json", "onfail": "cache"},
                        headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    if resp.status_code in (400, 404):
        raise MetarError(f"AVWX doesn't recognise {icao}. Check the code.")
    if resp.status_code == 401:
        raise MetarError("The AVWX token was rejected. Check AVWX_TOKEN.")
    if resp.status_code != 200:
        raise MetarError(f"AVWX returned an error ({resp.status_code}). Try again in a minute.")
    d = resp.json()

    def val(key):
        item = d.get(key) or {}
        return item.get("value") if isinstance(item, dict) else None

    vis = val("visibility")
    vis_unit = (d.get("units") or {}).get("visibility", "sm")
    if vis is None:
        vis_km = 10.0
    elif vis_unit == "m":
        vis_km = round(vis / 1000, 1)
    else:
        vis_km = round(vis * SM_TO_KM, 1)

    layers = [(c.get("type", ""), (c.get("altitude") or 0) * 100 if c.get("altitude") is not None else None)
              for c in (d.get("clouds") or [])]
    wdir = d.get("wind_direction") or {}
    return Observation(
        station=icao,
        raw=d.get("raw", ""),
        name=((d.get("info") or {}).get("name") or ""),
        observed=(d.get("time") or {}).get("dt", ""),
        wind_kt=float(val("wind_speed") or 0),
        wind_dir=wdir.get("repr", "") if isinstance(wdir, dict) else "",
        gust_kt=val("wind_gust"),
        vis_km=vis_km,
        temp_c=val("temperature"),
        dew_c=val("dewpoint"),
        ceiling_ft=ceiling_from(layers),
        clouds=[{"cover": c, "base_ft": b} for c, b in layers],
        source="AVWX",
    )


def fetch(icao: str, avwx_token: str | None = None) -> Observation:
    icao = normalise_icao(icao)
    try:
        return _from_avwx(icao, avwx_token) if avwx_token else _from_awc(icao)
    except requests.RequestException as exc:
        raise MetarError("Couldn't reach the weather service. Check your connection and try again.") from exc


# --- Raw METAR tokens, for the decoded strip -----------------------------------

TOKEN_KINDS = [
    ("wind", re.compile(r"^(\d{3}|VRB)\d{2,3}(G\d{2,3})?(KT|MPS)$")),
    ("vis", re.compile(r"^(\d{4}|\d{1,2}SM|\d/\dSM|\d \d/\dSM|M?1/4SM|P6SM|CAVOK)$")),
    ("cloud", re.compile(r"^(FEW|SCT|BKN|OVC|VV)\d{3}")),
    ("temp", re.compile(r"^M?\d{2}/(M?\d{2})?$")),
]


def tokenise(raw: str) -> list[dict]:
    """Split a raw METAR and tag the groups the readouts refer to."""
    out = []
    for tok in raw.split():
        kind = next((k for k, rx in TOKEN_KINDS if rx.match(tok)), None)
        out.append({"text": tok, "kind": kind})
    return out
