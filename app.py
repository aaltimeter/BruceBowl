from flask import Flask, redirect, render_template_string, request
from gpiozero import OutputDevice
from time import sleep
from datetime import datetime, date, timedelta
import sqlite3
import threading

app = Flask(__name__)

pump = OutputDevice(17, initial_value=False)
pump_lock = threading.Lock()

ML_PER_SECOND = 22.1
ML_PER_OUNCE = 29.57
DB_FILE = "bruce_bowl.db"


def db_connect():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS waterings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ounces REAL NOT NULL,
            seconds REAL NOT NULL,
            action TEXT DEFAULT 'dispense',
            note TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY,
            dog_name TEXT NOT NULL,
            dose_oz REAL NOT NULL,
            lockout_minutes INTEGER NOT NULL
        )
    """)

    cur.execute("PRAGMA table_info(waterings)")
    columns = [row[1] for row in cur.fetchall()]

    if "action" not in columns:
        cur.execute("ALTER TABLE waterings ADD COLUMN action TEXT DEFAULT 'dispense'")

    if "note" not in columns:
        cur.execute("ALTER TABLE waterings ADD COLUMN note TEXT DEFAULT ''")

    cur.execute("SELECT COUNT(*) FROM profile WHERE id=1")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO profile (id, dog_name, dose_oz, lockout_minutes) VALUES (1, 'Bruce', 3, 60)"
        )

    conn.commit()
    conn.close()


def get_profile():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT dog_name, dose_oz, lockout_minutes FROM profile WHERE id=1")
    row = cur.fetchone()
    conn.close()
    return {"dog_name": row[0], "dose_oz": row[1], "lockout_minutes": row[2]}


def dispense_oz(oz):
    seconds = (oz * ML_PER_OUNCE) / ML_PER_SECOND

    with pump_lock:
        pump.on()
        sleep(seconds)
        pump.off()

    return seconds


def log_event(oz, seconds, action="dispense", note=""):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO waterings (timestamp, ounces, seconds, action, note) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), oz, seconds, action, note)
    )

    conn.commit()
    conn.close()


def get_last_successful_drink():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT timestamp FROM waterings
        WHERE ounces > 0 AND action IN ('dispense', 'override')
        ORDER BY id DESC LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    return datetime.fromisoformat(row[0]) if row else None


def get_lockout_status(profile):
    last_drink = get_last_successful_drink()

    if last_drink is None:
        return {
            "locked": False,
            "remaining_seconds": 0,
            "remaining_text": "Ready",
            "last_drink_text": "None yet"
        }

    lockout_seconds = profile["lockout_minutes"] * 60
    elapsed = (datetime.now() - last_drink).total_seconds()
    remaining = max(0, lockout_seconds - elapsed)

    if remaining <= 0:
        return {
            "locked": False,
            "remaining_seconds": 0,
            "remaining_text": "Ready",
            "last_drink_text": last_drink.strftime("%I:%M:%S %p")
        }

    mins = int(remaining // 60)
    secs = int(remaining % 60)

    return {
        "locked": True,
        "remaining_seconds": int(remaining),
        "remaining_text": f"{mins}m {secs:02d}s",
        "last_drink_text": last_drink.strftime("%I:%M:%S %p")
    }


def get_stats():
    conn = db_connect()
    cur = conn.cursor()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    cur.execute("SELECT COUNT(*), COALESCE(SUM(ounces),0) FROM waterings WHERE ounces > 0")
    total_count, lifetime_oz = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(ounces),0) FROM waterings WHERE DATE(timestamp)=? AND ounces > 0",
        (today,)
    )
    today_count, today_oz = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(ounces),0) FROM waterings WHERE DATE(timestamp)=? AND ounces > 0",
        (yesterday,)
    )
    yesterday_count, yesterday_oz = cur.fetchone()

    cur.execute(
        "SELECT timestamp, ounces, seconds, action FROM waterings WHERE DATE(timestamp)=? ORDER BY id DESC",
        (today,)
    )
    rows = cur.fetchall()

    conn.close()

    events = []
    for ts, oz, seconds, action in rows:
        t = datetime.fromisoformat(ts).strftime("%I:%M:%S %p")

        if action == "denied":
            events.append(f"{t} — Denied: locked out")
        elif action == "override":
            events.append(f"{t} — OVERRIDE dispensed {oz:g} oz")
        else:
            events.append(f"{t} — Dispensed {oz:g} oz")

    return {
        "total_count": total_count,
        "lifetime_oz": lifetime_oz,
        "today_count": today_count,
        "today_oz": today_oz,
        "yesterday_count": yesterday_count,
        "yesterday_oz": yesterday_oz,
        "events": events,
    }


PAGE = """
<!doctype html>
<html>
<head>
<title>Bruce Bowl</title>
<meta name="viewport" content="width=device-width, initial-scale=1">

<style>
body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #101820;
    color: #f4f4f4;
}

.container {
    max-width: 520px;
    margin: auto;
    padding: 22px;
}

h1 {
    text-align: center;
    font-size: 34px;
    margin-bottom: 6px;
}

.subtitle {
    text-align: center;
    color: #9fb3c8;
    margin-bottom: 24px;
}

.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}

.card {
    background: #1b2a38;
    border-radius: 18px;
    padding: 18px;
    text-align: center;
    box-shadow: 0 4px 14px rgba(0,0,0,.25);
}

.label {
    color: #9fb3c8;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.value {
    font-size: 30px;
    font-weight: bold;
    margin-top: 8px;
}

.status-ready {
    color: #3ee87a;
}

.status-locked {
    color: #ff7676;
}

.main-button {
    width: 100%;
    border: none;
    border-radius: 18px;
    padding: 26px;
    font-size: 30px;
    font-weight: bold;
    color: white;
    background: #27ae60;
    margin-top: 22px;
}

.main-button:disabled {
    background: #4c5966;
    color: #9aa6b2;
}

details {
    margin-top: 18px;
    background: #162331;
    border-radius: 18px;
    padding: 16px;
}

summary {
    font-size: 22px;
    font-weight: bold;
    cursor: pointer;
}

details[open] summary {
    margin-bottom: 16px;
}

.override-box {
    background: #33210f;
    border-radius: 18px;
    padding: 18px;
    text-align: center;
}

.reset-box {
    margin-top: 16px;
    background: #2a1720;
    border-radius: 18px;
    padding: 18px;
    text-align: center;
}

input[type=range] {
    width: 100%;
}

.slider-row {
    margin: 18px 0;
}

.slider-value {
    font-size: 26px;
    font-weight: bold;
    text-align: center;
}

.save-button {
    width: 100%;
    border: none;
    border-radius: 18px;
    padding: 20px;
    font-size: 22px;
    font-weight: bold;
    color: white;
    background: #2f80ed;
    margin-top: 12px;
}

.event {
    border-bottom: 1px solid #2d3e50;
    padding: 10px 0;
    font-size: 14px;
}

.event:last-child {
    border-bottom: none;
}
</style>
</head>

<body>
<div class="container">

<h1>Bruce Bowl</h1>
<div class="subtitle">{{ dog_name }} Hydration Control</div>

<div class="grid">
    <div class="card">
        <div class="label">Today</div>
        <div class="value">{{ today_oz }} oz</div>
    </div>

    <div class="card">
        <div class="label">Drinks Today</div>
        <div class="value">{{ today_count }}</div>
    </div>

    <div class="card">
        <div class="label">Last Drink</div>
        <div class="value">{{ last_drink }}</div>
    </div>

    <div class="card">
        <div class="label">Next Water</div>
        <div id="nextWater" class="value {% if locked %}status-locked{% else %}status-ready{% endif %}">
            {{ remaining_text }}
        </div>
    </div>
</div>

<form action="/dispense" method="post">
    <button class="main-button dispense-btn" {% if locked %}disabled{% endif %}>
        Dispense {{ dose_oz }} oz
    </button>
</form>

<details>
    <summary>Override Controls</summary>

    <div class="override-box">
        <div class="label" style="color:#ffd08a;">
            Slide fully right to override and dispense {{ dose_oz }} oz
        </div>
        <form id="overrideForm" action="/override" method="post">
            <input type="range" min="0" max="100" value="0" id="overrideSlider">
        </form>
    </div>

    <div class="reset-box">
        <div class="label" style="color:#ffb3b3;">
            Slide fully right to reset today's drinks
        </div>
        <form id="resetForm" action="/reset_today" method="post">
            <input type="range" min="0" max="100" value="0" id="resetSlider">
        </form>
    </div>
</details>

<details>
    <summary>Bruce Profile</summary>

    <form action="/profile" method="post">
        <div class="slider-row">
            <div class="label">Water Per Drink</div>
            <div class="slider-value"><span id="doseValue">{{ dose_oz }}</span> oz</div>
            <input type="range" name="dose_oz" min="2" max="12" step="1" value="{{ dose_oz }}" id="doseSlider">
        </div>

        <div class="slider-row">
            <div class="label">Time Between Drinks</div>
            <div class="slider-value"><span id="timeValue">{{ lockout_minutes }}</span> min</div>
            <input type="range" name="lockout_minutes" min="15" max="90" step="15" value="{{ lockout_minutes }}" id="timeSlider">
        </div>

        <button class="save-button" type="submit">Save Profile</button>
    </form>
</details>

<details>
    <summary>Water History</summary>

    <h2>Today's Drinks</h2>
    {% if events %}
        {% for event in events %}
            <div class="event">{{ event }}</div>
        {% endfor %}
    {% else %}
        <div class="event">No drinks logged today.</div>
    {% endif %}

    <h2>Yesterday's Drinks</h2>
    <div class="grid">
        <div class="card">
            <div class="label">Times</div>
            <div class="value">{{ yesterday_count }}</div>
        </div>
        <div class="card">
            <div class="label">Ounces</div>
            <div class="value">{{ yesterday_oz }} oz</div>
        </div>
    </div>

    <h2>Lifetime</h2>
    <div class="grid">
        <div class="card">
            <div class="label">Events</div>
            <div class="value">{{ total_count }}</div>
        </div>
        <div class="card">
            <div class="label">Ounces</div>
            <div class="value">{{ lifetime_oz }} oz</div>
        </div>
    </div>
</details>

</div>

<script>
let remaining = {{ remaining_seconds }};
const nextWaterEl = document.getElementById("nextWater");
const dispenseButtons = document.querySelectorAll(".dispense-btn");

function updateCountdown() {
    if (remaining <= 0) {
        nextWaterEl.innerHTML = "Ready";
        nextWaterEl.className = "value status-ready";
        dispenseButtons.forEach(btn => btn.disabled = false);
        return;
    }

    let mins = Math.floor(remaining / 60);
    let secs = remaining % 60;

    nextWaterEl.innerHTML = mins + "m " + String(secs).padStart(2, "0") + "s";
    nextWaterEl.className = "value status-locked";
    dispenseButtons.forEach(btn => btn.disabled = true);

    remaining--;
}

updateCountdown();
setInterval(updateCountdown, 1000);

document.getElementById("doseSlider").addEventListener("input", function() {
    document.getElementById("doseValue").innerText = this.value;
});

document.getElementById("timeSlider").addEventListener("input", function() {
    document.getElementById("timeValue").innerText = this.value;
});

document.getElementById("overrideSlider").addEventListener("change", function() {
    if (this.value >= 95 && confirm("Override lockout and dispense now?")) {
        document.getElementById("overrideForm").submit();
    } else {
        this.value = 0;
    }
});

document.getElementById("resetSlider").addEventListener("change", function() {
    if (this.value >= 95 && confirm("Reset today's drink log?")) {
        document.getElementById("resetForm").submit();
    } else {
        this.value = 0;
    }
});
</script>

</body>
</html>
"""


@app.route("/")
def home():
    init_db()
    profile = get_profile()
    lockout = get_lockout_status(profile)
    stats = get_stats()

    return render_template_string(
        PAGE,
        dog_name=profile["dog_name"],
        dose_oz=int(profile["dose_oz"]),
        lockout_minutes=profile["lockout_minutes"],
        locked=lockout["locked"],
        remaining_text=lockout["remaining_text"],
        remaining_seconds=lockout["remaining_seconds"],
        last_drink=lockout["last_drink_text"],
        today_oz=round(stats["today_oz"], 2),
        today_count=stats["today_count"],
        yesterday_oz=round(stats["yesterday_oz"], 2),
        yesterday_count=stats["yesterday_count"],
        lifetime_oz=round(stats["lifetime_oz"], 2),
        total_count=stats["total_count"],
        events=stats["events"],
    )


@app.route("/profile", methods=["POST"])
def update_profile():
    dose_oz = float(request.form.get("dose_oz", 3))
    lockout_minutes = int(request.form.get("lockout_minutes", 60))

    dose_oz = max(2, min(12, dose_oz))
    lockout_minutes = max(15, min(90, lockout_minutes))

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        "UPDATE profile SET dose_oz=?, lockout_minutes=? WHERE id=1",
        (dose_oz, lockout_minutes)
    )

    conn.commit()
    conn.close()

    return redirect("/")


@app.route("/dispense", methods=["POST"])
def dispense():
    profile = get_profile()
    lockout = get_lockout_status(profile)

    if lockout["locked"]:
        log_event(0, 0, action="denied", note="Normal dispense denied during lockout")
        return redirect("/")

    oz = profile["dose_oz"]
    seconds = dispense_oz(oz)
    log_event(oz, seconds, action="dispense", note="Normal dispense")

    return redirect("/")


@app.route("/override", methods=["POST"])
def override():
    profile = get_profile()
    oz = profile["dose_oz"]

    seconds = dispense_oz(oz)
    log_event(oz, seconds, action="override", note="Emergency override")

    return redirect("/")


@app.route("/reset_today", methods=["POST"])
def reset_today():
    conn = db_connect()
    cur = conn.cursor()

    today = date.today().isoformat()

    cur.execute(
        "DELETE FROM waterings WHERE DATE(timestamp)=?",
        (today,)
    )

    conn.commit()
    conn.close()

    return redirect("/")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
