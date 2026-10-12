# ICAO Weather Risk

Type an airport's ICAO code and get its latest METAR, decoded, with a risk rating for wind, visibility and cloud ceiling.

The result page shows the raw METAR with each group linked to its decoded readout. Hover `27014G26KT` and the wind gauge lights up; hover the wind gauge and the group lights up. Each readout is an instrument style tape with the operating limits marked, and the FAA flight category (VFR, MVFR, IFR, LIFR) sits next to the overall rating.

## How the rating works

Two checks run side by side and the worse one wins.

**Operating limits**

| Readout | Moderate | High |
|---|---|---|
| Wind | 15 kt or more | 30 kt or more |
| Gusts | 25 kt or more | 35 kt or more |
| Visibility | under 5 km | under 1.6 km |
| Ceiling | under 1,000 ft | under 500 ft |

**Trained model.** A scikit-learn random forest (`models/weather_risk_model.pkl`) trained on wind speed, visibility and temperature. It catches combinations the fixed limits miss, like moderate wind in low visibility. It never sees gusts or ceiling, so the rules cover those. The page tells you which check drove the result.

## Weather data

- With no setup, the app reads METARs from NOAA's Aviation Weather Center API, which needs no key.
- Set `AVWX_TOKEN` to use [AVWX](https://avwx.rest) instead. Both sources go through the same parser, and visibility is converted to kilometres whichever units the station reports in.

## Accounts

Lookups are public. An account adds one thing: the home page keeps your last twelve stations for a one click recheck. Passwords are hashed with Werkzeug's PBKDF2. Accounts live in a JSON file (`instance/users.json` by default), which is fine for a demo; point `USERS_FILE` at a persistent disk or swap in a database for real use.

## Project layout

```
app/
  __init__.py     App factory and routes
  metar.py        AWC and AVWX clients, normalised Observation, METAR tokeniser
  risk.py         Operating limits, flight category, model wrapper
  users.py        JSON user store with lookup history
  templates/      Jinja templates
  static/         CSS and self hosted B612 fonts
models/
  weather_risk_model.pkl
tests/
  test_app.py     Parsing, rules, routes, accounts (network calls mocked)
wsgi.py
```

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

export FLASK_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python wsgi.py                     # http://localhost:5000
pytest
```

See `.env.example` for every variable.

## Deploy

The `Procfile` runs `gunicorn wsgi:app`, so Render, Railway or Heroku work as is. Set `FLASK_SECRET_KEY`, and `AVWX_TOKEN` if you want AVWX.

`scikit-learn` is pinned to 1.7.1 because that's the version the model was saved with. Retrain before upgrading it.

## Design notes

- The page looks like a daylight aeronautical chart: cool grey paper with a faint grid, navy ink.
- Type is B612, the face Airbus commissioned for cockpit displays, with B612 Mono for the raw METAR. Both are self hosted.
- Colour only carries meaning: green, amber and red for risk, and the standard FAA colours for flight categories.
- The hover link between METAR groups and readouts is pure CSS (`:has()`), no JavaScript.

For situational awareness only. Always get an official briefing before flight.
