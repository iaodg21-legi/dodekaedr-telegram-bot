import os
import sqlite3
import threading
import http.server
import socketserver
import logging
import secrets
from datetime import datetime, time
from zoneinfo import ZoneInfo
from html import escape as h

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("dodekaedr")

# ============================================================
# CONFIG
# ============================================================
TZ = ZoneInfo("Europe/Prague")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "/var/data/dodekaedr.db")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "stangzk").strip().lower()

MORNING_DEFAULT = "07:00"
EVENING_DEFAULT = "21:00"

APP_LINK = os.getenv("APP_LINK", "").strip()

MODES = ["ZÁKLADNÍ", "TVRDÝ", "LEGIONÁŘSKÝ"]

PLANES = {
    1: "TĚLO",
    2: "NÁVYK",
    3: "STABILITA",
    4: "ČIN",
    5: "SMĚR",
    6: "ODVAHA",
    7: "ROZEZNÁNÍ",
    8: "HRANICE",
    9: "ODPOVĚDNOST",
    10: "PAMĚŤ",
    11: "PROPOJENÍ",
    12: "NASLOUCHÁNÍ",
}

SCENARIOS = {
    "ZÁKLADNÍ": {
        1: ("Tělo nelže. My ano.", "Udělej dnes jednu věc pro tělo vědomě."),
        2: ("Opakuješ to, čím se stáváš.", "Zachyť jeden automatismus a uprav ho."),
        3: ("Klid není slabost. Je to tvar.", "Zůstaň klidný v jedné napjaté situaci."),
        4: ("Úmysl nestačí.", "Udělej dnes jednu věc, kterou odkládáš."),
        5: ("Bez směru se pohyb mění v rozptyl.", "Napiš jednu větu o tom, kam směřuješ."),
        6: ("Odvaha není hluk. Je to krok.", "Udělej dnes jednu nepohodlnou věc."),
        7: ("Ne všechno, co cítíš, je pravda.", "Odděl dnes fakt od domněnky."),
        8: ("Bez hranic ztrácíš tvar.", "Jednou dnes řekni jasné „ne“."),
        9: ("Svoboda má důsledky.", "Přiznej dnes jeden důsledek bez výmluv."),
        10: ("Paměť je závazek.", "Připomeň si jednu lekci, kterou nechceš opustit."),
        11: ("Nikdo nežije izolovaně.", "Uvědom si dopad svého jednání na druhé."),
        12: ("Ticho je také čin.", "Dnes jen poslouchej, bez reakce."),
    },
    "TVRDÝ": {
        1: ("Tělo je základ, ne nástroj.", "Udělej pro tělo něco nepohodlného, ale správného."),
        2: ("Návyk je řetěz i opora.", "Zruš dnes jeden zbytečný automatismus."),
        3: ("Stabilita je disciplína, ne nálada.", "Udrž klid tam, kde bys dřív zrychlil."),
        4: ("Slova nic neudělají.", "Dokonči dnes jednu odkládanou věc."),
        5: ("Bez směru se ztrácíš.", "Pojmenuj dnešní směr jednou větou."),
        6: ("Komfort není argument.", "Udělej dnes krok navzdory odporu."),
        7: ("Pocit není důkaz.", "Odděl fakta od interpretací."),
        8: ("Bez hranic se rozplýváš.", "Dnes odmítni to, co ti bere tvar."),
        9: ("Odpovědnost není emoce.", "Přiznej důsledek a vezmi ho na sebe."),
        10: ("Zapomnění je pohodlné.", "Vrať si jednu lekci a drž ji."),
        11: ("Dopad se počítá.", "Dnes jednej tak, aby to unesl i druhý."),
        12: ("Naslouchej, než promluvíš.", "Dnes mlč a vnímej."),
    },
    "LEGIONÁŘSKÝ": {
        1: ("Tělo je bojiště disciplíny.", "Dnes tělo posílíš. Bez vyjednávání."),
        2: ("Návyk je osud.", "Dnes jeden špatný návyk zlomíš."),
        3: ("Stabilita je tvar pod tlakem.", "Dnes se nezlomíš v drobnosti."),
        4: ("Čin rozhoduje.", "Dnes uděláš to, co odkládáš."),
        5: ("Směr je závazek.", "Dnes řekneš, kam jdeš. Jednou větou."),
        6: ("Strach není omluva.", "Dnes uděláš nepohodlný krok."),
        7: ("Rozlišuj, nebo budeš veden.", "Dnes oddělíš fakt od projekce."),
        8: ("Hranice chrání tvar.", "Dnes jednou řekneš „dost“."),
        9: ("Odpovědnost se neptá.", "Dnes vezmeš důsledek bez výmluv."),
        10: ("Paměť drží identitu.", "Dnes si připomeneš lekci a nezradíš ji."),
        11: ("Propojení je síť důsledků.", "Dnes si uvědomíš, koho svým činem zasáhneš."),
        12: ("Ticho je síla.", "Dnes budeš jen poslouchat."),
    },
}

# ============================================================
# HEALTH SERVER (PORT binding)
# ============================================================
def start_health_server():
    port = int(os.getenv("PORT", "10000"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, fmt, *args):
            return

    httpd = socketserver.TCPServer(("", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

# ============================================================
# DB
# ============================================================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {r[1] for r in rows}

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                mode TEXT NOT NULL DEFAULT 'ZÁKLADNÍ',
                morning_time TEXT NOT NULL DEFAULT '07:00',
                evening_time TEXT NOT NULL DEFAULT '21:00',
                is_enabled INTEGER NOT NULL DEFAULT 1
            )
        """)

        # Kompatibilita:
        # - starší DB může mít rolls.mode jako NOT NULL
        # - scenario_mode je uzamčený režim dne
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rolls (
                chat_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                number INTEGER NOT NULL,
                plane TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'ZÁKLADNÍ',
                scenario_mode TEXT DEFAULT NULL,
                pending INTEGER NOT NULL DEFAULT 1,
                verdict TEXT DEFAULT NULL,
                rolled_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, day)
            )
        """)

        cols = _table_columns(conn, "rolls")

        if "number" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN number INTEGER NOT NULL DEFAULT 0;")
        if "plane" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN plane TEXT NOT NULL DEFAULT '';")
        if "mode" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN mode TEXT NOT NULL DEFAULT 'ZÁKLADNÍ';")
        if "scenario_mode" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN scenario_mode TEXT DEFAULT NULL;")
        if "pending" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN pending INTEGER NOT NULL DEFAULT 1;")
        if "verdict" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN verdict TEXT DEFAULT NULL;")
        if "rolled_at" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN rolled_at TEXT NOT NULL DEFAULT '';")

def upsert_user(chat_id: int):
    with db() as conn:
        conn.execute("""
            INSERT INTO users (chat_id) VALUES (?)
            ON CONFLICT(chat_id) DO NOTHING
        """, (chat_id,))

def get_user(chat_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT chat_id, mode, morning_time, evening_time, is_enabled FROM users WHERE chat_id=?",
            (chat_id,),
        ).fetchone()

def set_user_mode(chat_id: int, mode: str):
    with db() as conn:
        conn.execute("UPDATE users SET mode=? WHERE chat_id=?", (mode, chat_id))

def set_user_times(chat_id: int, morning: str, evening: str):
    with db() as conn:
        conn.execute(
            "UPDATE users SET morning_time=?, evening_time=? WHERE chat_id=?",
            (morning, evening, chat_id),
        )

def set_user_enabled(chat_id: int, enabled: bool):
    with db() as conn:
        conn.execute(
            "UPDATE users SET is_enabled=? WHERE chat_id=?",
            (1 if enabled else 0, chat_id),
        )

def today_str() -> str:
    return datetime.now(TZ).date().isoformat()

def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")

def get_today_roll(chat_id: int):
    with db() as conn:
        return conn.execute(
            """
            SELECT day, number, plane, mode, scenario_mode, pending, verdict
            FROM rolls
            WHERE chat_id=? AND day=?
            """,
            (chat_id, today_str()),
        ).fetchone()

def is_pending_today(chat_id: int) -> bool:
    row = get_today_roll(chat_id)
    if not row:
        return False
    return (int(row[5]) == 1) or (row[4] is None)

def save_pending_roll(chat_id: int, number: int):
    number = int(number)
    plane = PLANES[number]

    u = get_user(chat_id)
    user_mode = (u[1] if u else "ZÁKLADNÍ")
    if user_mode not in MODES:
        user_mode = "ZÁKLADNÍ"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO rolls
                (chat_id, day, number, plane, mode, scenario_mode, pending, verdict, rolled_at)
            VALUES
                (?, ?, ?, ?, ?, NULL, 1, NULL, ?)
            ON CONFLICT(chat_id, day) DO NOTHING
            """,
            (chat_id, today_str(), number, plane, user_mode, now_iso()),
        )

def ensure_today_roll(chat_id: int) -> tuple[int, str]:
    row = get_today_roll(chat_id)
    if row:
        _day, number, plane, _mode, _scenario_mode, _pending, _verdict = row
        return int(number), str(plane)

    number = daily_number(chat_id)
    save_pending_roll(chat_id, number)

    row2 = get_today_roll(chat_id)
    if row2:
        _day, number, plane, _mode, _scenario_mode, _pending, _verdict = row2
        return int(number), str(plane)

    return int(number), PLANES[int(number)]

def finalize_roll_mode(chat_id: int, chosen_mode: str):
    with db() as conn:
        conn.execute(
            """
            UPDATE rolls
            SET scenario_mode=?, mode=?, pending=0
            WHERE chat_id=? AND day=?
            """,
            (chosen_mode, chosen_mode, chat_id, today_str()),
        )

def set_verdict(chat_id: int, verdict: str):
    with db() as conn:
        conn.execute(
            """
            UPDATE rolls
            SET verdict=?
            WHERE chat_id=? AND day=?
            """,
            (verdict, chat_id, today_str()),
        )

def last_12(chat_id: int):
    with db() as conn:
        return conn.execute(
            """
            SELECT day, number, plane, verdict
            FROM rolls
            WHERE chat_id=?
            ORDER BY day DESC
            LIMIT 12
            """,
            (chat_id,),
        ).fetchall()

# ============================================================
# STATS
# ============================================================
def stats_user_verdict_counts(chat_id: int):
    with db() as conn:
        return conn.execute(
            """
            SELECT
                CASE WHEN verdict IS NULL THEN 'BEZ VERDIKTU' ELSE verdict END as v,
                COUNT(*) as c
            FROM rolls
            WHERE chat_id=?
            GROUP BY v
            ORDER BY c DESC
            """,
            (chat_id,),
        ).fetchall()

def stats_global_verdict_counts():
    with db() as conn:
        return conn.execute(
            """
            SELECT
                CASE WHEN verdict IS NULL THEN 'BEZ VERDIKTU' ELSE verdict END as v,
                COUNT(*) as c
            FROM rolls
            GROUP BY v
            ORDER BY c DESC
            """
        ).fetchall()

def stats_user_top_uhnul_planes(chat_id: int, limit: int = 5):
    with db() as conn:
        return conn.execute(
            """
            SELECT plane, COUNT(*) as c
            FROM rolls
            WHERE chat_id=? AND verdict='UHNUL'
            GROUP BY plane
            ORDER BY c DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()

def stats_global_top_uhnul_planes(limit: int = 5):
    with db() as conn:
        return conn.execute(
            """
            SELECT plane, COUNT(*) as c
            FROM rolls
            WHERE verdict='UHNUL'
            GROUP BY plane
            ORDER BY c DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

def stats_global_mode_rates():
    with db() as conn:
        return conn.execute(
            """
            SELECT COALESCE(scenario_mode, mode) as m,
                   SUM(CASE WHEN verdict='OBSTÁL' THEN 1 ELSE 0 END) as ok,
                   COUNT(*) as n
            FROM rolls
            WHERE verdict IS NOT NULL
            GROUP BY m
            ORDER BY n DESC
            """
        ).fetchall()

def stats_counts_total(chat_id: int | None = None):
    with db() as conn:
        if chat_id is None:
            return conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM rolls WHERE chat_id=?", (chat_id,)).fetchone()[0]

def stats_users_total():
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if n:
            return n
        return conn.execute("SELECT COUNT(DISTINCT chat_id) FROM rolls").fetchone()[0]

def stats_streaks(chat_id: int):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT verdict
            FROM rolls
            WHERE chat_id=?
            ORDER BY day DESC
            """,
            (chat_id,),
        ).fetchall()

    streak_obstal = 0
    streak_bez_uhnul = 0

    for (verdict,) in rows:
        if verdict == "OBSTÁL":
            streak_obstal += 1
            streak_bez_uhnul += 1
            continue
        if verdict == "UHNUL":
            break
        streak_bez_uhnul += 1
        break

    return streak_obstal, streak_bez_uhnul

# ============================================================
# CORE (random roll)
# ============================================================
def daily_number(chat_id: int) -> int:
    # skutečně náhodný hod 1..12
    return secrets.randbelow(12) + 1

# ============================================================
# COPY / UX
# ============================================================
def start_text() -> str:
    link_line = f"\n\n<b>Odkaz</b>\n{h(APP_LINK)}" if APP_LINK else ""
    return (
        "<b>DODEKAEDR</b>\n"
        "Digitální disciplína reality.\n\n"
        "<b>Jak postupovat dnes</b>\n"
        "1️⃣ <b>/hod</b> — určí rovinu dne (nelze změnit)\n"
        "2️⃣ <b>Zvol tón</b> — ZÁKLADNÍ / TVRDÝ / LEGIONÁŘSKÝ\n"
        "3️⃣ <b>Jednej</b> — drž rovinu celý den\n"
        "4️⃣ <b>Večer verdikt</b> — obstál jsi, nebo jsi uhnul\n\n"
        "<b>Příkazy</b>\n"
        "• /hod — denní hod (1× denně)\n"
        "• /dnes — ukáže dnešní stav\n"
        "• /rezim — změní výchozí tón / uzamkne dnešek (když čeká)\n"
        "• /historie — posledních 12 dní\n"
        "• /stat — statistika\n"
        "• /cas 07:00 21:00 — rytmus dne\n"
        "• /stop — zastaví připomínky\n\n"
        "Nevybíráš si rovinu.\n"
        "Pouze ji přijmeš — nebo uhneš."
        f"{link_line}"
    )

def msg_no_roll_yet() -> str:
    return "Dnes ještě nepadl hod.\n\n<b>Krok 1️⃣:</b> napiš /hod."

def msg_pending_pick_mode() -> str:
    return (
        "<b>Krok 2️⃣ — zvol tón dne</b>\n"
        "Tón určuje jazyk a tlak.\n"
        "Princip zůstává."
    )

def msg_mode_default_set(mode: str) -> str:
    return f"Výchozí tón nastaven: {mode}"

def msg_paused() -> str:
    return "Zastaveno.\nAž budeš chtít znovu: /start."

def msg_times_help() -> str:
    return (
        "Nastav rytmus (HH:MM)\n\n"
        "Použij:\n"
        "/cas 07:00 21:00\n\n"
        "První čas = ráno, druhý = večer."
    )

def msg_times_set(morning: str, evening: str) -> str:
    return f"Nastaveno.\nRáno: {morning}\nVečer: {evening}"

def copy_morning(default_mode: str) -> str:
    return (
        "<b>Dnes nezačínej myšlením.</b>\n\n"
        "🎲 <b>Krok 1:</b> Hoď kostkou.\n"
        "Pak zvol tón a jednej."
    )

def copy_evening(mode: str) -> str:
    if mode == "LEGIONÁŘSKÝ":
        return "Den je uzavřen.\n\nObstál jsi, nebo jsi uhnul?"
    if mode == "TVRDÝ":
        return "Teď bez výmluv.\n\nObstál jsi, nebo jsi uhnul?"
    return "Závěr dne.\n\nObstál jsi, nebo jsi uhnul?"

def verdict_reply(mode: str, verdict: str) -> str:
    if verdict == "OBSTÁL":
        if mode == "LEGIONÁŘSKÝ":
            return "Udržel jsi linii."
        if mode == "TVRDÝ":
            return "Udržel jsi tvar."
        return "Zůstal jsi ve směru."
    else:
        if mode == "LEGIONÁŘSKÝ":
            return "Zapsáno.\nTeď s tím pracuj."
        if mode == "TVRDÝ":
            return "Pravda zapsaná.\nBez omluv."
        return "Zapsáno.\nZítra znovu."

def format_scenario(mode: str, number: int) -> str:
    plane = PLANES[number]
    impulse, task = SCENARIOS[mode][number]
    return (
        f"<b>🎲 {number} — {h(plane)}</b>\n"
        f"<i>{h(impulse)}</i>\n\n"
        f"<b>{h(task)}</b>\n"
        f"<i>Uzamčeno do 24:00.</i>"
    )

def mode_keyboard(prefix: str = "pick:") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ZÁKLADNÍ", callback_data=f"{prefix}ZÁKLADNÍ")],
        [InlineKeyboardButton("TVRDÝ", callback_data=f"{prefix}TVRDÝ")],
        [InlineKeyboardButton("LEGIONÁŘSKÝ", callback_data=f"{prefix}LEGIONÁŘSKÝ")],
    ])

def action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PŘIJÍMÁM", callback_data="accept")],
        [InlineKeyboardButton("VERDIKT", callback_data="verdict")],
    ])

def valid_hhmm(s: str) -> bool:
    try:
        hh, mm = s.split(":")
        h0 = int(hh)
        m0 = int(mm)
        return 0 <= h0 <= 23 and 0 <= m0 <= 59
    except Exception:
        return False

def is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.username and u.username.strip().lower() == ADMIN_USERNAME)

# ============================================================
# FLOW HELPERS
# ============================================================
async def show_today_status(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    row = get_today_roll(chat_id)
    if not row:
        await context.bot.send_message(chat_id=chat_id, text=msg_no_roll_yet(), parse_mode=ParseMode.HTML)
        return

    _day, number, _plane, mode_db, scenario_mode, pending, _verdict = row
    chosen_mode = scenario_mode or mode_db

    if int(pending) == 1 or not scenario_mode:
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg_pending_pick_mode(),
            parse_mode=ParseMode.HTML,
            reply_markup=mode_keyboard(prefix="pick:"),
        )
        return

    msg = format_scenario(chosen_mode, int(number))
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML, reply_markup=action_keyboard())

# ============================================================
# HANDLERS
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    await update.message.reply_text(start_text(), parse_mode=ParseMode.HTML)

    await schedule_user_jobs(context, chat_id)
    if getattr(context, "job_queue", None) is None:
        await update.message.reply_text("Pozn.: připomínky jsou teď vypnuté (hosting nemá job queue).")
    else:
        await update.message.reply_text("Ráno a večer přijde připomínka.\nRytmus změníš: /cas 07:00 21:00")

async def cmd_hod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    number, plane = ensure_today_roll(chat_id)

    row = get_today_roll(chat_id)
    if not row:
        await update.message.reply_text("Hod se nepodařilo uložit (DB). Zkus znovu.")
        return

    _day, number_db, _plane_db, _mode_db, scenario_mode, pending, _verdict = row

    if int(pending) == 1 or not scenario_mode:
        await update.message.reply_text(
            f"<b>Krok 1️⃣ — rovina dne padla</b>\n\n"
            f"🎲 <b>{int(number_db)} — {h(plane)}</b>\n\n"
            f"{msg_pending_pick_mode()}",
            parse_mode=ParseMode.HTML,
            reply_markup=mode_keyboard(prefix="pick:"),
        )
        return

    msg = format_scenario(scenario_mode, int(number_db))
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=action_keyboard())

async def cmd_dnes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    await show_today_status(context, chat_id)

async def cmd_rezim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    if is_pending_today(chat_id):
        await update.message.reply_text(
            "<b>Dnes už rovina padla.</b>\n\n"
            "Vyber tón pro dnešek:",
            parse_mode=ParseMode.HTML,
            reply_markup=mode_keyboard(prefix="pick:"),
        )
        return

    await update.message.reply_text(
        "Zvol výchozí tón:",
        reply_markup=mode_keyboard(prefix="default:"),
    )

async def cmd_historie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = last_12(chat_id)
    if not rows:
        await update.message.reply_text("Zatím žádná stopa.")
        return

    def dot(v):
        if v == "OBSTÁL":
            return "●"
        if v == "UHNUL":
            return "○"
        return "·"

    lines = ["Posledních 12 dní:\n"]
    for d, num, plane, verdict in rows:
        lines.append(f"{dot(verdict)}  {d} — {num} {plane}")
    await update.message.reply_text("\n".join(lines))

async def cmd_cas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    parts = (update.message.text or "").strip().split()
    if len(parts) == 1:
        await update.message.reply_text(msg_times_help())
        return
    if len(parts) != 3:
        await update.message.reply_text("Použití: /cas 07:00 21:00")
        return

    morning, evening = parts[1], parts[2]
    if not valid_hhmm(morning) or not valid_hhmm(evening):
        await update.message.reply_text("Špatný formát. Použij HH:MM (např. 07:00 21:00).")
        return

    set_user_times(chat_id, morning, evening)
    await schedule_user_jobs(context, chat_id, force_reschedule=True)
    await update.message.reply_text(msg_times_set(morning, evening))

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    set_user_enabled(chat_id, False)
    await unschedule_user_jobs(context, chat_id)
    await update.message.reply_text(msg_paused())

async def cmd_stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    if is_admin(update):
        users = stats_users_total()
        total = stats_counts_total(None)
        verdicts = stats_global_verdict_counts()
        top_uhnul = stats_global_top_uhnul_planes()
        mode_rates = stats_global_mode_rates()

        v_lines = [f"• {v}: {c}" for v, c in verdicts] or ["—"]
        t_lines = [f"• {plane}: {c}" for plane, c in top_uhnul] or ["—"]

        m_lines = []
        for mode, ok, n in mode_rates:
            rate = (ok / n * 100.0) if n else 0.0
            m_lines.append(f"• {mode}: {ok}/{n} ({rate:.0f} %)")
        if not m_lines:
            m_lines = ["—"]

        text = (
            "<b>/stat — Globální přehled</b>\n\n"
            f"Uživatelé: <b>{users}</b>\n"
            f"Záznamy: <b>{total}</b>\n\n"
            "<b>Verdikty</b>\n" + "\n".join(v_lines) +
            "\n\n<b>Nejčastější UHNUL (roviny)</b>\n" + "\n".join(t_lines) +
            "\n\n<b>Úspěšnost podle režimu (jen tam, kde je verdikt)</b>\n" + "\n".join(m_lines)
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    total = stats_counts_total(chat_id)
    verdicts = stats_user_verdict_counts(chat_id)
    streak_obstal, streak_bez_uhnul = stats_streaks(chat_id)
    top_uhnul = stats_user_top_uhnul_planes(chat_id)

    ok_ = next((c for v, c in verdicts if v == "OBSTÁL"), 0)
    uhnul = next((c for v, c in verdicts if v == "UHNUL"), 0)
    rate = (ok_ / (ok_ + uhnul) * 100.0) if (ok_ + uhnul) else 0.0

    top_lines = [f"• {plane}: {c}" for plane, c in top_uhnul] or ["—"]
    v_lines = [f"• {v}: {c}" for v, c in verdicts] or ["—"]

    text = (
        "<b>/stat — Tvoje stopa</b>\n\n"
        f"Záznamy: <b>{total}</b>\n\n"
        "<b>Verdikty</b>\n" + "\n".join(v_lines) +
        "\n\n<b>Streak</b>\n"
        f"• OBSTÁL v řadě: <b>{streak_obstal}</b>\n"
        f"• Bez UHNUL: <b>{streak_bez_uhnul}</b>\n\n"
        f"Úspěšnost (z verdiktů): <b>{rate:.0f} %</b>\n\n"
        "<b>Kde nejčastěji uhýbáš</b>\n" + "\n".join(top_lines)
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ============================================================
# CALLBACKS
# ============================================================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = (query.data or "").strip()

    upsert_user(chat_id)

    if data == "accept":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Přijato.\n\nTeď už nehledej únik.")
        return

    if data == "verdict":
        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text(msg_no_roll_yet(), parse_mode=ParseMode.HTML)
            return

        _day, _number, _plane, mode_db, scenario_mode, pending, _verdict = row
        chosen_mode = scenario_mode or mode_db

        if int(pending) == 1 or not scenario_mode:
            await query.message.reply_text(
                "Nejdřív zvol tón pro dnešek.",
                reply_markup=mode_keyboard(prefix="pick:"),
            )
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
            [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
        ])
        await query.message.reply_text(copy_evening(chosen_mode), reply_markup=kb)
        return

    if data.startswith("v:"):
        verdict = data.split(":", 1)[1]
        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text(msg_no_roll_yet(), parse_mode=ParseMode.HTML)
            return

        _day, _number, _plane, mode_db, scenario_mode, pending, _verdict = row
        chosen_mode = scenario_mode or mode_db

        if int(pending) == 1 or not scenario_mode:
            await query.message.reply_text("Nejdřív zvol tón pro dnešek.", reply_markup=mode_keyboard(prefix="pick:"))
            return

        set_verdict(chat_id, verdict)
        await query.message.reply_text(verdict_reply(chosen_mode, verdict))
        return

    if data.startswith("pick:"):
        mode = data.split(":", 1)[1]
        if mode not in MODES:
            return

        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text("Nejdřív hoď: /hod")
            return

        _day, number, _plane, _mode_db, scenario_mode, pending, _verdict = row

        if int(pending) == 0 and scenario_mode:
            set_user_mode(chat_id, mode)
            await query.message.reply_text(f"Dnešek už je uzamčený.\n{msg_mode_default_set(mode)}")
            return

        finalize_roll_mode(chat_id, mode)
        set_user_mode(chat_id, mode)

        msg = format_scenario(mode, int(number))
        await query.message.reply_text(f"Režim: {mode}")
        await query.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=action_keyboard())
        return

    if data.startswith("default:"):
        mode = data.split(":", 1)[1]
        if mode not in MODES:
            return
        set_user_mode(chat_id, mode)
        await query.message.reply_text(msg_mode_default_set(mode))
        return

    if data == "roll_now":
        number, plane = ensure_today_roll(chat_id)
        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text("Hod se nepodařilo uložit (DB). Zkus znovu.")
            return

        _day, number_db, _plane_db, _mode_db, scenario_mode, pending, _verdict = row
        if int(pending) == 1 or not scenario_mode:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"<b>Krok 1️⃣ — rovina dne padla</b>\n\n"
                     f"🎲 <b>{int(number_db)} — {h(plane)}</b>\n\n"
                     f"{msg_pending_pick_mode()}",
                parse_mode=ParseMode.HTML,
                reply_markup=mode_keyboard(prefix="pick:"),
            )
            return

        await show_today_status(context, chat_id)
        return

# ============================================================
# JOB QUEUE (safe)
# ============================================================
async def schedule_user_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int, force_reschedule: bool = False):
    jq = getattr(context, "job_queue", None)
    if jq is None:
        return

    if force_reschedule:
        await unschedule_user_jobs(context, chat_id)

    u = get_user(chat_id)
    if not u or int(u[4]) != 1:
        return

    morning_str = u[2] or MORNING_DEFAULT
    evening_str = u[3] or EVENING_DEFAULT

    morning_t = time(int(morning_str.split(":")[0]), int(morning_str.split(":")[1]), tzinfo=TZ)
    evening_t = time(int(evening_str.split(":")[0]), int(evening_str.split(":")[1]), tzinfo=TZ)

    jname_m = f"morning:{chat_id}"
    jname_e = f"evening:{chat_id}"

    if not force_reschedule and any(j.name == jname_m for j in jq.jobs()):
        return

    jq.run_daily(morning_job, time=morning_t, name=jname_m, chat_id=chat_id)
    jq.run_daily(evening_job, time=evening_t, name=jname_e, chat_id=chat_id)

async def unschedule_user_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    jq = getattr(context, "job_queue", None)
    if jq is None:
        return
    for j in list(jq.jobs()):
        if j.name in (f"morning:{chat_id}", f"evening:{chat_id}"):
            j.schedule_removal()

async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or int(u[4]) != 1:
        return
    default_mode = u[1]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("HOĎ", callback_data="roll_now")]])
    await context.bot.send_message(chat_id=chat_id, text=copy_morning(default_mode), parse_mode=ParseMode.HTML, reply_markup=kb)

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or int(u[4]) != 1:
        return

    row = get_today_roll(chat_id)
    if not row:
        await context.bot.send_message(chat_id=chat_id, text="Bez hodu není stopa.\nPoužij /hod.")
        return

    _day, _number, _plane, mode_db, scenario_mode, pending, _verdict = row
    chosen_mode = scenario_mode or mode_db

    if int(pending) == 1 or not scenario_mode:
        await context.bot.send_message(chat_id=chat_id, text="Dnes ještě chybí tón.\nZvol ho: /rezim")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
        [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
    ])
    await context.bot.send_message(chat_id=chat_id, text=copy_evening(chosen_mode), reply_markup=kb)

# ============================================================
# ERROR HANDLER
# ============================================================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled exception", exc_info=context.error)

# ============================================================
# MAIN
# ============================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Chybí BOT_TOKEN (nastav jako env proměnnou).")

    start_health_server()
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hod", cmd_hod))
    app.add_handler(CommandHandler("dnes", cmd_dnes))
    app.add_handler(CommandHandler("rezim", cmd_rezim))
    app.add_handler(CommandHandler("historie", cmd_historie))
    app.add_handler(CommandHandler("stat", cmd_stat))
    app.add_handler(CommandHandler("cas", cmd_cas))
    app.add_handler(CommandHandler("stop", cmd_stop))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
