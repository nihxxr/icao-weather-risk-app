from unittest.mock import patch, MagicMock

import pytest

from app import create_app, metar
from app.risk import flight_category, rule_check

VOBL = metar.Observation(
    station="VOBL", raw="VOBL 121330Z 27014G26KT 4000 HZ BKN015 SCT100 28/19 Q1012 NOSIG",
    name="Bengaluru Intl", observed="2026-10-12 13:30Z", wind_kt=14, wind_dir="270", gust_kt=26,
    vis_km=4.0, temp_c=28, dew_c=19, ceiling_ft=1500, source="test",
)


def fake_fetch(code, token=None):
    code = metar.normalise_icao(code)
    if code == "ZZZZ":
        raise metar.MetarError("No current METAR for ZZZZ.")
    return VOBL


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "FETCH": fake_fetch, "USERS_FILE": str(tmp_path / "users.json")})
    return app.test_client()


def test_flight_category():
    assert flight_category(16, None) == "VFR"
    assert flight_category(16, 2500) == "MVFR"
    assert flight_category(3, None) == "IFR"
    assert flight_category(16, 400) == "LIFR"


def test_rules():
    assert rule_check(5, 10)[0] == 0
    assert rule_check(18, 10)[0] == 1
    assert rule_check(5, 1.0)[0] == 2
    assert rule_check(5, 10, ceiling=800)[0] == 1


def test_bad_code():
    with pytest.raises(metar.MetarError):
        metar.normalise_icao("JFK")


def test_tokenise():
    kinds = {t["text"]: t["kind"] for t in metar.tokenise(VOBL.raw)}
    assert kinds["27014G26KT"] == "wind"
    assert kinds["4000"] == "vis"
    assert kinds["BKN015"] == "cloud"
    assert kinds["28/19"] == "temp"


def test_awc_parse():
    resp = MagicMock(status_code=200, content=b"x")
    resp.json.return_value = [{
        "rawOb": "KJFK 121251Z 31012KT 10SM FEW250 18/06 A3012", "name": "New York/JF Kennedy Intl, NY, US",
        "reportTime": "2026-10-12T12:51:00Z", "wspd": 12, "wdir": 310, "visib": "10+",
        "temp": 18, "dewp": 6, "clouds": [{"cover": "FEW", "base": 25000}],
    }]
    with patch("app.metar.requests.get", return_value=resp):
        obs = metar.fetch("kjfk")
    assert obs.station == "KJFK" and obs.wind_dir == "310"
    assert obs.vis_km == pytest.approx(16.1, abs=0.1)
    assert obs.ceiling_ft is None
    assert obs.name == "New York/JF Kennedy Intl"


def test_avwx_parse_metres():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "raw": "VOBL 121330Z 27014KT 4000 HZ BKN015 28/19 Q1012", "time": {"dt": "2026-10-12T13:30:00Z"},
        "wind_speed": {"value": 14}, "wind_direction": {"repr": "270"}, "wind_gust": None,
        "visibility": {"value": 4000}, "units": {"visibility": "m"},
        "temperature": {"value": 28}, "dewpoint": {"value": 19},
        "clouds": [{"type": "BKN", "altitude": 15}], "info": {"name": "Kempegowda Intl"},
    }
    with patch("app.metar.requests.get", return_value=resp):
        obs = metar.fetch("VOBL", avwx_token="t")
    assert obs.vis_km == 4.0 and obs.ceiling_ft == 1500 and obs.gust_kt is None


def test_pages(client):
    for path in ("/", "/manual", "/login", "/signup"):
        assert client.get(path).status_code == 200


def test_station_lookup_is_public(client):
    r = client.get("/station?icao=vobl")
    assert r.status_code == 200
    assert b"High risk" in r.data  # model rates 4 km haze higher than the rules
    assert b'data-kind="wind"' in r.data


def test_station_error(client):
    r = client.get("/station?icao=ZZZZ")
    assert r.status_code == 400 and b"No current METAR" in r.data


def test_manual(client):
    r = client.post("/manual", data={"wind": "35", "vis": "8", "temp": "20"})
    assert b"High risk" in r.data
    assert client.post("/manual", data={"wind": "x"}).status_code == 400


def test_report(client):
    r = client.get("/report?station=VOBL&wind=14&vis=4&temp=28&gust=26&ceiling=1500")
    assert r.headers["Content-Disposition"].startswith("attachment")
    assert b"Risk level: High" in r.data and b"\\n" not in r.data


def test_signup_and_history(client):
    r = client.post("/signup", data={"username": "pilot", "password": "longenough"}, follow_redirects=True)
    assert b"pilot" in r.data
    client.get("/station?icao=VOBL")
    home = client.get("/")
    assert b"Your recent checks" in home.data and b"VOBL" in home.data
    client.get("/logout")
    assert client.post("/login", data={"username": "pilot", "password": "wrong"}).status_code == 401
    assert client.post("/login", data={"username": "pilot", "password": "longenough"}).status_code == 302
