# ICAO Weather Risk Analysis

A Flask web app that pulls live METAR reports for any ICAO airport code and scores the
weather risk for aviation, combining a trained scikit-learn model with ICAO rule thresholds.

## What it does

Enter an ICAO code (`KJFK`, `VOBL`, `EGLL`) and the app fetches the current METAR from the
AVWX API, extracts wind speed, visibility and temperature, and returns a risk level.

Two signals are combined:

- **Rule check** — flags high risk above 30kt wind or below 5SM visibility, moderate above
  15kt or below 10SM, mirroring standard ICAO operating thresholds.
- **ML model** — a scikit-learn classifier (`weather_risk_model.pkl`) trained on the same
  three features, which catches combinations the fixed thresholds miss.

Results can be downloaded as a report. User accounts are supported so pilots can keep their
own lookup history.

## Stack

Flask · scikit-learn · joblib · pandas · AVWX API · gunicorn

## Running locally

```bash
pip install -r requirements.txt

export AVWX_TOKEN=your_token_here          # free key from https://avwx.rest
export FLASK_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

python app.py
```

Open http://localhost:5000.

See `.env.example` for the full list of variables.

## Deploying

The repo includes a `Procfile`, so it runs on any Heroku-style host (Render, Railway):

```
web: gunicorn app:app
```

Set `AVWX_TOKEN` and `FLASK_SECRET_KEY` in the host's environment settings. Note that the
local `users.json` store does not survive restarts on ephemeral filesystems — swap it for a
database if you need accounts to persist.

## Notes

Credentials are read from the environment, never committed. Passwords are hashed with
Werkzeug's PBKDF2 before storage.
