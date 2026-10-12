from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for

from . import metar
from .risk import RiskModel, assess, metric_levels, LEVELS
from .users import UserStore

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = [("VOBL", "Bengaluru"), ("KJFK", "New York JFK"), ("EGLL", "London Heathrow"),
            ("YBBN", "Brisbane"), ("VIDP", "Delhi")]


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
        AVWX_TOKEN=os.environ.get("AVWX_TOKEN") or None,
        USERS_FILE=os.environ.get("USERS_FILE", str(ROOT / "instance" / "users.json")),
        MODEL_PATH=str(ROOT / "models" / "weather_risk_model.pkl"),
        FETCH=metar.fetch,
    )
    if config:
        app.config.update(config)

    model = RiskModel(Path(app.config["MODEL_PATH"]))
    users = UserStore(Path(app.config["USERS_FILE"]))

    @app.context_processor
    def inject():
        user = session.get("user")
        return {"user": user, "history": users.history(user) if user else [], "examples": EXAMPLES}

    def render_assessment(obs: metar.Observation, live: bool):
        a = assess(model, obs.wind_kt, obs.vis_km, obs.temp_c, obs.gust_kt, obs.ceiling_ft)
        levels = metric_levels(obs.wind_kt, obs.vis_km, obs.gust_kt, obs.ceiling_ft)
        return render_template("result.html", obs=obs, a=a, live=live, levels=levels,
                               tokens=metar.tokenise(obs.raw) if obs.raw else [])

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/station")
    def station():
        code = request.args.get("icao", "")
        try:
            obs = app.config["FETCH"](code, app.config["AVWX_TOKEN"])
        except metar.MetarError as exc:
            return render_template("index.html", error=str(exc), icao=code), 400
        if session.get("user"):
            a = assess(model, obs.wind_kt, obs.vis_km, obs.temp_c, obs.gust_kt, obs.ceiling_ft)
            users.record(session["user"], obs.station, a.label, a.category)
        return render_assessment(obs, live=True)

    @app.route("/manual", methods=["GET", "POST"])
    def manual():
        if request.method == "GET":
            return render_template("manual.html", values={})
        values = request.form.to_dict()
        try:
            obs = metar.Observation(
                station="Manual",
                wind_kt=float(values["wind"]),
                gust_kt=float(values["gust"]) if values.get("gust") else None,
                vis_km=float(values["vis"]),
                temp_c=float(values["temp"]),
                ceiling_ft=int(float(values["ceiling"])) if values.get("ceiling") else None,
            )
        except (KeyError, ValueError):
            return render_template("manual.html", values=values,
                                   error="Enter numbers for wind, visibility and temperature."), 400
        return render_assessment(obs, live=False)

    @app.get("/report")
    def report():
        q = request.args
        try:
            wind, vis, temp = float(q["wind"]), float(q["vis"]), float(q["temp"])
        except (KeyError, ValueError):
            return redirect(url_for("index"))
        gust = float(q["gust"]) if q.get("gust") else None
        ceil = int(q["ceiling"]) if q.get("ceiling") else None
        a = assess(model, wind, vis, temp, gust, ceil)
        station = q.get("station", "Manual")
        lines = [
            f"Weather risk report: {station}",
            f"Observed: {q.get('observed') or 'n/a'}",
            f"METAR: {q.get('raw') or 'n/a'}",
            "",
            f"Risk level: {a.label}",
            f"Flight category: {a.category}",
            f"Wind: {wind:g} kt" + (f", gusts {gust:g} kt" if gust else ""),
            f"Visibility: {vis:g} km",
            f"Ceiling: {ceil} ft" if ceil is not None else "Ceiling: none reported",
            f"Temperature: {temp:g} C",
            "",
            "Why:",
            *[f"  - [{r['level']}] {r['text']}" for r in a.reasons],
            *([] if a.reasons else ["  - All values inside normal operating limits"]),
            "",
            f"Rule check: {LEVELS[a.rule_level]}   Model: {LEVELS[a.model_level] if a.model_level is not None else 'n/a'}",
            "For situational awareness only. Not a substitute for an official briefing.",
        ]
        fname = f"weather-risk-{station.lower()}.txt"
        return Response("\n".join(lines) + "\n", mimetype="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if len(username) < 3 or len(password) < 8:
                return render_template("auth.html", mode="signup",
                                       error="Use at least 3 characters for the username and 8 for the password."), 400
            if not users.create(username, password):
                return render_template("auth.html", mode="signup", error="That username is taken."), 400
            session["user"] = username
            flash("Account created. Stations you check now appear on the home page.")
            return redirect(url_for("index"))
        return render_template("auth.html", mode="signup")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            if users.verify(username, request.form.get("password", "")):
                session["user"] = username
                return redirect(url_for("index"))
            return render_template("auth.html", mode="login", error="Wrong username or password."), 401
        return render_template("auth.html", mode="login")

    @app.get("/logout")
    def logout():
        session.pop("user", None)
        return redirect(url_for("index"))

    return app
