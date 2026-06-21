from flask import Flask, redirect, render_template_string, request
from gpiozero import OutputDevice
from time import sleep
from datetime import datetime, date
import sqlite3

app = Flask(__name__)

pump = OutputDevice(17, initial_value=False)

ML_PER_SECOND = 22.1
ML_PER_OUNCE = 29.57
DB_FILE = "bruce_bowl.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS waterings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ounces REAL NOT NULL,
            seconds REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def dispense_oz(oz):
    seconds = (oz * ML_PER_OUNCE) / ML_PER_SECOND
    pump.on()
    sleep(seconds)
    pump.off()
    return seconds

def log_watering(oz, seconds):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO waterings (timestamp, ounces, seconds) VALUES (?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), oz, seconds)
    )
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    today = date.today().isoformat()

    cur.execute("SELECT COUNT(*), COALESCE(SUM(ounces), 0) FROM waterings")
    total_count, lifetime_oz = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(ounces), 0) FROM waterings WHERE DATE(timestamp)=?",
        (today,)
    )
    today_count, today_oz = cur.fetchone()

    cur.execute("SELECT timestamp, ounces, seconds FROM waterings ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()

    events = []
    for ts, oz, seconds in rows:
        dt = datetime.fromisoformat(ts)
        events.append(f"{dt.strftime('%I:%M:%S %p')} — Dispensed {oz:g} oz ({seconds:.2f} sec)")

    return total_count, lifetime_oz, today_count, today_oz, events

PAGE = """
<!doctype html>
<html>
<head>
<title>Bruce Bowl</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family:Arial,sans-serif; background:#101820; color:#f4f4f4; }
.container { max-width:520px; margin:auto; padding:22px; }
h1 { text-align:center; font-size:34px; margin-bottom:6px; }
.subtitle { text-align:center; color:#9fb3c8; margin-bottom:24px; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.card { background:#1b2a38; border-radius:18px; padding:18px; text-align:center; box-shadow:0 4px 14px rgba(0,0,0,.25); }
.label { color:#9fb3c8; font-size:14px; text-transform:uppercase; letter-spacing:1px; }
.value { font-size:30px; font-weight:bold; margin-top:8px; }
.buttons { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:22px; }
button { border:none; border-radius:18px; padding:22px; font-size:22px; font-weight:bold; color:white; background:#2f80ed; }
button.big { grid-column:span 2; background:#27ae60; font-size:28px; }
button.warn { background:#c0392b; }
.log { margin-top:24px; background:#162331; border-radius:18px; padding:16px; }
.log h2 { margin-top:0; }
.event { border-bottom:1px solid #2d3e50; padding:10px 0; color:#dce8f2; font-size:14px; }
.event:last-child { border-bottom:none; }
</style>
</head>
<body>
<div class="container">
    <h1>Bruce Bowl</h1>
    <div class="subtitle">Smart Hydration Control</div>

    <div class="grid">
        <div class="card">
            <div class="label">Today</div>
            <div class="value">{{ today_oz }} oz</div>
        </div>
        <div class="card">
            <div class="label">Waterings Today</div>
            <div class="value">{{ today_count }}</div>
        </div>
        <div class="card">
            <div class="label">Lifetime</div>
            <div class="value">{{ lifetime_oz }} oz</div>
        </div>
        <div class="card">
            <div class="label">Total Events</div>
            <div class="value">{{ total_count }}</div>
        </div>
    </div>

    <form class="buttons" action="/dispense" method="post">
        <button class="big" name="oz" value="4">Dispense 4 oz</button>
        <button name="oz" value="6">6 oz</button>
        <button class="warn" name="oz" value="8">8 oz</button>
    </form>

    <div class="log">
        <h2>Recent Log</h2>
        {% for event in events %}
            <div class="event">{{ event }}</div>
        {% endfor %}
    </div>
</div>
</body>
</html>
"""

@app.route("/")
def home():
    total_count, lifetime_oz, today_count, today_oz, events = get_stats()
    return render_template_string(
        PAGE,
        total_count=total_count,
        lifetime_oz=round(lifetime_oz, 2),
        today_count=today_count,
        today_oz=round(today_oz, 2),
        events=events
    )

@app.route("/dispense", methods=["POST"])
def dispense():
    oz = float(request.form.get("oz", 4))
    seconds = dispense_oz(oz)
    log_watering(oz, seconds)
    return redirect("/")

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
