from flask import Flask, render_template, request, redirect, url_for, session, send_file
import joblib
import os
import json
import requests

app = Flask(__name__)
app.secret_key = 'secret123'

model = joblib.load('weather_risk_model.pkl')
USER_FILE = "users.json"
AVWX_TOKEN = "ptP35Q34G9ENj6czvlH-hP1YSSHWPqoD2xnwfZzMFKw"

# ----------------- User Management -----------------
def load_users():
    if not os.path.exists(USER_FILE):
        return {}
    with open(USER_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USER_FILE, "w") as f:
        json.dump(users, f)

# ----------------- METAR via AVWX -----------------
def fetch_metar(icao_code):
    headers = {
        "Authorization": f"Bearer {AVWX_TOKEN}"
    }
    url = f"https://avwx.rest/api/metar/{icao_code.upper()}?options=&format=json&onfail=cache"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None, "Invalid ICAO code or AVWX API error"
        data = response.json()

        wind_speed = data['wind_speed']['value'] or 0
        visibility = data['visibility']['value'] or 10
        temperature = data['temperature']['value'] or 20

        return {
            "wind": wind_speed,
            "vis": round(visibility, 1),
            "temp": temperature
        }, None

    except Exception as e:
        return None, str(e)

# ----------------- Risk Logic -----------------
def icao_rule_check(wind, vis):
    if wind > 30 or vis < 5:
        return 2
    elif wind > 15 or vis < 10:
        return 1
    return 0

def combined_risk(wind, vis, temp):
    ml_result = model.predict([[wind, vis, temp]])[0]
    rule_result = icao_rule_check(wind, vis)
    return max(ml_result, rule_result)

# ----------------- Routes -----------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/predict', methods=['POST'])
def predict():
    if 'user' not in session:
        return redirect(url_for('login'))

    wind = float(request.form['wind'])
    vis = float(request.form['vis'])
    temp = float(request.form['temp'])
    risk_level = combined_risk(wind, vis, temp)
    label = ['Low', 'Moderate', 'High'][risk_level]
    color = ['success', 'warning', 'danger'][risk_level]
    chart_color = ['"rgba(40, 167, 69, 0.7)"', '"rgba(255, 193, 7, 0.7)"', '"rgba(220, 53, 69, 0.7)"'][risk_level]

    return render_template(
        'result.html',
        risk=label,
        color=color,
        wind=wind,
        vis=vis,
        temp=temp,
        risk_value=risk_level + 1,  # just for bar height
        chart_color=chart_color
    )


@app.route('/download')
def download():
    if 'user' not in session:
        return redirect(url_for('login'))
    risk = request.args.get('risk', 'Unknown')
    file_path = 'result.txt'
    with open(file_path, 'w') as f:
        f.write(f"ICAO Weather Risk Analysis Result:\\nPredicted Risk Level: {risk}")
    return send_file(file_path, as_attachment=True)

@app.route('/signup', methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        users = load_users()
        if username in users:
            return render_template("signup.html", error="Username already exists.")
        users[username] = password
        save_users(users)
        session["user"] = username
        return redirect(url_for("index"))
    return render_template("signup.html")

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        users = load_users()
        if username in users and users[username] == password:
            session["user"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid Credentials")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route('/fetch_metar', methods=["POST"])
def fetch_metar_data():
    if 'user' not in session:
        return redirect(url_for('login'))
    icao = request.form["icao"]
    data, error = fetch_metar(icao)
    if error:
        return render_template("index.html", metar_error=error)
    return render_template("index.html", wind=data["wind"], vis=data["vis"], temp=data["temp"])

# ----------------- Main -----------------
if __name__ == '__main__':
    app.run(debug=True)
