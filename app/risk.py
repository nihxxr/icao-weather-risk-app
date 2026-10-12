"""Risk scoring: fixed operating limits combined with the trained classifier.

The classifier was trained on three features: wind speed (kt), visibility (km)
and temperature (deg C). Rule checks also look at gusts and cloud ceiling,
which the model never saw. The final level is whichever source is worse.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd

LEVELS = ("Low", "Moderate", "High")
MODEL_FEATURES = ["wind_speed_kts", "visibility_km", "temperature_C"]

# (metric, high-risk test, moderate test, human label)
WIND_HIGH, WIND_MOD = 30, 15
GUST_HIGH, GUST_MOD = 35, 25
VIS_HIGH, VIS_MOD = 1.6, 5.0          # km; roughly 1 SM and 3 SM
CEIL_HIGH, CEIL_MOD = 500, 1000       # ft


@dataclass
class Assessment:
    level: int
    rule_level: int
    model_level: int | None
    reasons: list
    category: str

    @property
    def label(self) -> str:
        return LEVELS[self.level]


def flight_category(vis_km: float, ceiling_ft: int | None) -> str:
    """FAA flight category from visibility and ceiling."""
    vis_sm = vis_km / 1.609344
    ceil = ceiling_ft if ceiling_ft is not None else 99999
    if ceil < 500 or vis_sm < 1:
        return "LIFR"
    if ceil < 1000 or vis_sm < 3:
        return "IFR"
    if ceil <= 3000 or vis_sm <= 5:
        return "MVFR"
    return "VFR"


def rule_check(wind, vis_km, gust=None, ceiling=None) -> tuple[int, list]:
    level, reasons = 0, []

    def flag(lvl, text):
        nonlocal level
        level = max(level, lvl)
        reasons.append({"level": LEVELS[lvl], "text": text})

    if wind >= WIND_HIGH:
        flag(2, f"Wind {wind:.0f} kt is at or above the {WIND_HIGH} kt limit")
    elif wind >= WIND_MOD:
        flag(1, f"Wind {wind:.0f} kt is above {WIND_MOD} kt")

    if gust is not None:
        if gust >= GUST_HIGH:
            flag(2, f"Gusts to {gust:.0f} kt")
        elif gust >= GUST_MOD:
            flag(1, f"Gusts to {gust:.0f} kt")

    if vis_km < VIS_HIGH:
        flag(2, f"Visibility {vis_km:g} km is below {VIS_HIGH:g} km")
    elif vis_km < VIS_MOD:
        flag(1, f"Visibility {vis_km:g} km is below {VIS_MOD:g} km")

    if ceiling is not None:
        if ceiling < CEIL_HIGH:
            flag(2, f"Ceiling {ceiling} ft is below {CEIL_HIGH} ft")
        elif ceiling < CEIL_MOD:
            flag(1, f"Ceiling {ceiling} ft is below {CEIL_MOD} ft")

    return level, reasons


class RiskModel:
    def __init__(self, path: Path):
        self.estimator = joblib.load(path) if path.exists() else None

    def predict(self, wind, vis_km, temp) -> int | None:
        if self.estimator is None or temp is None:
            return None
        row = pd.DataFrame([[wind, vis_km, temp]], columns=MODEL_FEATURES)
        return int(self.estimator.predict(row)[0])


def assess(model: RiskModel, wind, vis_km, temp, gust=None, ceiling=None) -> Assessment:
    rule_level, reasons = rule_check(wind, vis_km, gust, ceiling)
    model_level = model.predict(wind, vis_km, temp)
    level = max(rule_level, model_level or 0)
    if model_level is not None and model_level > rule_level:
        reasons.append({"level": LEVELS[model_level],
                        "text": "The trained model rates this mix of wind, visibility and temperature higher than the fixed limits do"})
    return Assessment(level, rule_level, model_level, reasons, flight_category(vis_km, ceiling))


def metric_levels(wind, vis_km, gust=None, ceiling=None) -> dict:
    """Per-readout level (0, 1, 2) so each gauge can show its own state."""
    def band(value, high, mod, lower_is_worse=False):
        if value is None:
            return 0
        if lower_is_worse:
            return 2 if value < high else 1 if value < mod else 0
        return 2 if value >= high else 1 if value >= mod else 0

    return {
        "wind": max(band(wind, WIND_HIGH, WIND_MOD), band(gust, GUST_HIGH, GUST_MOD)),
        "vis": band(vis_km, VIS_HIGH, VIS_MOD, lower_is_worse=True),
        "cloud": band(ceiling, CEIL_HIGH, CEIL_MOD, lower_is_worse=True),
        "temp": 0,
    }
