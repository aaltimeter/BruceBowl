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

LOCKOUT_MINUTES = 45
LOCKOUT_SECONDS = LOCKOUT_MINUTES * 60


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
            seconds REAL NOT NULL
        )
    """)

    cur.execute("PRAGMA table_info(waterings)")
    columns = [row[1] for row in cur.fetchall()]

    if "action" not in columns:
        cur.execute("ALTER TABLE waterings ADD COLUMN action TEXT DEFAULT 'dispense'")

    if "note" not in columns:
        cur.execute("ALTER TABLE waterings ADD COLUMN note TEXT DEFAULT ''")

    conn.commit()
    conn.close()


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
        """
        INSERT INTO waterings (timestamp, ounces, seconds, action, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (datetime.now().isoformat(timespec="seconds"), oz, seconds, action, note)
    )

    conn.commit()
    conn.close()


def get_last_successful_drink():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT timestamp
        FROM waterings
        WHERE ounces > 0
        AND action IN ('dispense', 'override')
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return datetime.fromisoformat(row[0])


def get_lockout_status():
    last_drink = get_last_successful_drink()

    if last_drink is None:
        return {
            "locked": False,
            "remaining_seconds": 0,
            "remaining_text": "Ready",
            "last_drink_text": "None yet"
        }

    now = datetime.now()
    elapsed = (now - last_drink).total_seconds()
    remaining = max(0, LOCKOUT_SECONDS - elapsed)

    if remaining <= 0:
        remaining_text = "Ready"
        locked = False
    else:
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        remaining_text = f"{minutes}m {seconds}s"
        locked = True

    return {
        "locked": locked,
        "remaining_seconds": int(remaining),
        "remaining_text": remaining_text,
        "last_drink_text": last_drink.strftime("%I:%M:%S %p")
    }


def get_stats():
    conn = db_connect()
    cur = conn.cursor()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(ounces), 0)
        FROM waterings
        WHERE ounces > 0
    """)
    total_count, lifetime_oz = cur.fetchone()

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(ounces), 0)
        FROM waterings
        WHERE DATE(timestamp)=?
        AND ounces > 0
    """, (today,))
    today_count, today_oz = cur.fetchone()

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(ounces), 0)
        FROM waterings
        WHERE DATE(timestamp)=?
        AND ounces > 0
    """, (yesterday,))
    yesterday_count, yesterday_oz = cur.fetchone()

    cur.execute("""
        SELECT timestamp, ounces, seconds, action, note
        FROM waterings
        WHERE DATE(timestamp)=?
        ORDER BY id DESC
    """, (today,))
    today_rows = cur.fetchall()

    conn.close()

    today_events = []
    for ts, oz, seconds, action, note in today_rows:
        dt = datetime.fromisoformat(ts)
        time_text = dt.strftime("%I:%M:%S %p")

        if action == "denied":
            today_events.append(f"{time_text} — Denied: locked out")
        elif action == "override":
            today_events.append(f"{time_text} — OVERRIDE dispensed {oz:g} oz ({seconds:.2f} sec)")
        else:
            today_events.append(f"{time_text} — Dispensed {oz:g} oz ({seconds:.2f} sec)")

    return {
        "total_count": total_count,
        "lifetime_oz": lifetime_oz,
        "today_count": today_count,
        "today_oz": today_oz,
        "yesterday_count": yesterday_count,
        "yesterday_oz": yesterday_oz,
        "today_events": today_events,
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

.buttons {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 22px;
}

button {
    border: none;
    border-radius: 18px;
    padding: 22px;
    font-size: 22px;
    font-weight: bold;
    color: white;
    background: #2f80ed;
}

button.big {
    grid-column: span 2;
    background: #27ae60;
    font-size: 28px;
}

button.warn {
    background: #c0392b;
}

button:disabled {
    background: #4c5966;
    color: #9aa6b2;
    cursor: not-allowed;
}

.section {
    margin-top: 24px;
    background: #162331;
    border-radius: 18px;
    padding: 16px;
}

.section h2 {
    margin-top: 0;
}

.event {
    border-bottom: 1px solid #2d3e50;
    padding: 10px 0;
    color: #dce8f2;
    font-size: 14px;
}

.event:last-child {
    border-bottom: none;
}

.reset-box {
    margin-top: 24px;
    background: #2a1720;
    border-radius: 18px;
    padding: 18px;
    text-align: center;
}

.override-box {
    margin-top: 24px;
    background: #33210f;
    border-radius: 18px;
    padding: 18px;
    text-align: center;
}

.reset-label {
    color: #ffb3b3;
    font-size: 14px;
    margin-bottom: 10px;
}

.override-label {
    color: #ffd08a;
    font-size: 14px;
    margin-bottom: 10px;
}

input[type=range] {
    width: 100%;
}
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
            <div class="label">Drinks Today</div>
            <div class="value">{{ today_count }}</div>
        </div>

        <div class="card">
            <div class="label">Last Drink</div>
            <div class="value">{{ last_drink }}</div>
        </div>

        <div class="card">
            <div class="label">Next Water</div>
            {% if locked %}
                <div class="value status-locked">{{ remaining_text }}</div>
            {% else %}
                <div class="value status-ready">Ready</div>
            {% endif %}
        </div>
    </div>

    <form class="buttons" action="/dispense" method="post">
        <button class="big" name="oz" value="4" {% if locked %}disabled{% endif %}>
            Dispense 4 oz
        </button>

        <button name="oz" value="6" {% if locked %}disabled{% endif %}>
            6 oz
        </button>

        <button class="warn" name="oz" value="8" {% if locked %}disabled{% endif %}>
            8 oz
        </button>
    </form>

    {% if locked %}
    <div class="override-box">
        <div class="override-label">
            Emergency override: slide fully right to dispense 4 oz now
        </div>
        <form id="overrideForm" action="/override" method="post">
            <input type="range" min="0" max="100" value="0" id="overrideSlider">
        </form>
    </div>
    {% endif %}

    <div class="reset-box">
        <div class="reset-label">Slide fully right to reset today's drinks</div>
        <form id="resetForm" action="/reset_today" method="post">
            <input type="range" min="0" max="100" value="0" id="resetSlider">
        </form>
    </div>

    <div class="section">
        <h2>Today's Drinks</h2>
        {% if today_events %}
            {% for event in today_events %}
                <div class="event">{{ event }}</div>
            {% endfor %}
        {% else %}
            <div class="event">No drinks logged today.</div>
        {% endif %}
    </div>

    <div class="section">
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
    </div>

    <div class="section">
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
    </div>

</div>

<script>
const resetSlider = document.getElementById("resetSlider");
const resetForm = document.getElementById("resetForm");

resetSlider.addEventListener("change", function() {
    if (resetSlider.value >= 95) {
        if (confirm("Reset today's drink log? This cannot be undone.")) {
            resetForm.submit();
        } else {
            resetSlider.value = 0;
        }
    } else {
        resetSlider.value = 0;
    }
});

const overrideSlider = document.getElementById("overrideSlider");
const overrideForm = document.getElementById("overrideForm");

if (overrideSlider) {
    overrideSlider.addEventListener("change", function() {
        if (overrideSlider.value >= 95) {
            if (confirm("Emergency override: dispense 4 oz now?")) {
                overrideForm.submit();
            } else {
                overrideSlider.value = 0;
            }
        } else {
            overrideSlider.value = 0;
        }
    });
}
</script>

</body>
</html>
"""


@app.route("/")
def home():
    stats = get_stats()
    lockout = get_lockout_status()

    return render_template_string(
        PAGE,
        total_count=stats["total_count"],
        lifetime_oz=round(stats["lifetime_oz"], 2),
        today_count=stats["today_count"],
        today_oz=round(stats["today_oz"], 2),
        yesterday_count=stats["yesterday_count"],
        yesterday_oz=round(stats["yesterday_oz"], 2),
        today_events=stats["today_events"],
        locked=lockout["locked"],
        remaining_text=lockout["remaining_text"],
        last_drink=lockout["last_drink_text"],
    )


@app.route("/dispense", methods=["POST"])
def dispense():
    lockout = get_lockout_status()

    if lockout["locked"]:
        log_event(0, 0, action="denied", note="Normal dispense denied during lockout")
        return redirect("/")

    oz = float(request.form.get("oz", 4))
    seconds = dispense_oz(oz)
    log_event(oz, seconds, action="dispense", note="Normal dispense")

    return redirect("/")


@app.route("/override", methods=["POST"])
def override():
    oz = 4
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
