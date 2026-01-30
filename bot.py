import os
import sqlite3
import threading
import http.server
import socketserver
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
# CONFIG
# ============================================================
TZ = ZoneInfo("Europe/Prague")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Persist volume path (Render/Railway apod.)
DB_PATH = os.getenv("DB_PATH", "/var/data/dodekaedr.db")

# Admin username bez @
ADMIN_USERNAME = "stangzk"

MORNING_DEFAULT = "07:00"
EVENING_DEFAULT = "21:00"

# volitelně: link na app / bot / web
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
        12: ("Ticho je také čin.", "Jednou dnes jen poslouchej — bez reakce."),
    },
    "TVRDÝ": {
        1: ("Tělo je základ, ne nástroj.", "Udělej pro tělo něco nepohodlného, ale správného."),
        2: ("Návyk je řetěz i opora.", "Zruš dnes jeden zbytečný automatismus."),
        3: ("Stabilita je disciplína, ne nálada.", "Udrž klid tam, kde bys dřív zrychlil."),
        4: ("Slova nic neudělají.", "Dokonči dnes jednu odkládanou věc."),
        5: ("Bez směru se ztrácíš.", "Pojmenuj dnešní směr jednou větou."),
        6: ("Komfort není argument.", "Udělej dnes krok navzdory odporu."),
        7: ("Pocit není důkaz.", "Odděl fakta od interpretací."),
        8: ("Bez hranic se rozplýváš.", "Jednou dnes odmítni to, co ti bere tvar."),
        9: ("Odpovědnost není emoce.", "Přiznej důsledek a vezmi ho na sebe."),
        10: ("Zapomnění je pohodlné.", "Vrať si jednu lekci a drž ji."),
        11: ("Dopad se počítá.", "Dnes jednej tak, aby to unesl i druhý."),
        12: ("Naslouchej, než promluvíš.", "Dnes jednou mlč a vnímej."),
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
        12: ("Ticho je síla.", "Dnes jednou budeš jen poslouchat."),
    },
}

# ============================================================
# Health server (PORT binding)
# ============================================================
def start_health_server():
    """
    Někteří hosteři vyžadují otevřený port (PORT), jinak službu označí jako mrtvou.
    """
    port = int(os.getenv("PORT", "10000"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, fmt, *args):
            return

    class ReuseTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = ReuseTCPServer(("", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

# ============================================================
# DB
# ============================================================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _table_columns(conn: sqlite3.Connection, table: str):
    cols = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {c[1] for c in cols}

def init_db():
    """
    - vytvoří tabulky
    - bezpečně migruje chybějící sloupce
    """
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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS rolls (
                chat_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                number INTEGER NOT NULL,
                plane TEXT NOT NULL,
                scenario_mode TEXT DEFAULT NULL,
                pending INTEGER NOT NULL DEFAULT 1,
                verdict TEXT DEFAULT NULL,
                rolled_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, day)
            )
        """)

        # migrace
        cols = _table_columns(conn, "rolls")
        if "scenario_mode" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN scenario_mode TEXT DEFAULT NULL;")
        if "pending" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN pending INTEGER NOT NULL DEFAULT 0;")
        if "verdict" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN verdict TEXT DEFAULT NULL;")
        if "plane" not in cols:
            conn.execute("ALTER TABLE rolls ADD COLUMN plane TEXT NOT NULL DEFAULT '';")
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
        conn.execute("UPDATE users SET is_enabled=? WHERE chat_id=?", (1 if enabled else 0, chat_id))

def today_str() -> str:
    return datetime.now(TZ).date().isoformat()

def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")

def get_today_roll(chat_id: int):
    """
    day, number, plane, scenario_mode, pending, verdict
    """
    with db() as conn:
        return conn.execute(
            "SELECT day, number, plane, scenario_mode, pending, verdict FROM rolls WHERE chat_id=? AND day=?",
            (chat_id, today_str()),
        ).fetchone()

def has_roll_today(chat_id: int) -> bool:
    return get_today_roll(chat_id) is not None

def is_pending_today(chat_id: int) -> bool:
    row = get_today_roll(chat_id)
    return (row is not None) and (int(row[4]) == 1 or not row[3])

def save_pending_roll(chat_id: int, number: int):
    plane = PLANES[number]
    with db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO rolls (chat_id, day, number, plane, scenario_mode, pending, verdict, rolled_at)
            VALUES (?, ?, ?, ?, NULL, 1, NULL, ?)
        """, (chat_id, today_str(), number, plane, now_iso()))

def finalize_roll_mode(chat_id: int, mode: str):
    with db() as conn:
        conn.execute("""
            UPDATE rolls
            SET scenario_mode=?, pending=0
            WHERE chat_id=? AND day=?
        """, (mode, chat_id, today_str()))

def set_verdict(chat_id: int, verdict: str):
    with db() as conn:
        conn.execute("""
            UPDATE rolls
            SET verdict=?
            WHERE chat_id=? AND day=?
        """, (verdict, chat_id, today_str()))

def last_12(chat_id: int):
    with db() as conn:
        return conn.execute("""
            SELECT day, number, plane, verdict
            FROM rolls
            WHERE chat_id=?
            ORDER BY day DESC
            LIMIT 12
        """, (chat_id,)).fetchall()

# ============================================================
# Core logic
# ============================================================
def daily_number(chat_id: int) -> int:
    # deterministický hod (stejné číslo pro uživatele v daný den)
    seed = int(datetime.now(TZ).strftime("%Y%m%d")) + int(chat_id)
    return (seed % 12) + 1

def valid_hhmm(s: str) -> bool:
    try:
        hh, mm = s.split(":")
        h0 = int(hh); m0 = int(mm)
        return 0 <= h0 <= 23 and 0 <= m0 <= 59
    except Exception:
        return False

def is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.username and u.username.lower() == ADMIN_USERNAME.lower())

# ============================================================
# Copy / UX
# ============================================================
def start_text() -> str:
    link_line = f"\n\n<b>Odkaz</b>\n{h(APP_LINK)}" if APP_LINK else ""
    return (
        "<b>DODEKAEDR</b>\n"
        "Digitální disciplína reality.\n\n"
        "Hod určuje rovinu dne.\n"
        "Nevybíráš si ji. Přijímáš ji.\n\n"
        "<b>Příkazy</b>\n"
        "• /hod — hod dne (1× denně)\n"
        "• /dnes — připomenout dnešní stav\n"
        "• /rezim — změnit výchozí tón / uzamknout dnešek (pokud čeká)\n"
        "• /historie — posledních 12 dní\n"
        "• /stat — statistika (tvoje; admin vidí globál)\n"
        "• /cas 07:00 21:00 — nastavit rytmus\n"
        "• /stop — zastavit připomínky\n\n"
        "Začni až ve chvíli, kdy uneseš důsledek."
        f"{link_line}"
    )

def msg_no_roll_yet() -> str:
    return "Dnes ještě nepadl hod.\nPoužij /hod."

def msg_pending_pick_mode() -> str:
    return "Rovina dne je určená.\nTeď zvol tón:"

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
    # vždy: nejdřív hod, pak volba tónu
    if default_mode == "LEGIONÁŘSKÝ":
        return "Dnes se ukáže charakter.\n\n🎲 Hoď. Pak zvol tón."
    if default_mode == "TVRDÝ":
        return "Dnes se počítá tvar.\n\n🎲 Hoď. Pak zvol tón."
    return "Dnes přijde rovina.\n\n🎲 Hoď. Pak zvol tón."

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

# ============================================================
# Flow helper: dnešní stav
# ============================================================
async def show_today_status(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    row = get_today_roll(chat_id)
    if not row:
        await context.bot.send_message(chat_id=chat_id, text=msg_no_roll_yet())
        return

    _day, number, _plane, scenario_mode, pending, _verdict = row
    if int(pending) == 1 or not scenario_mode:
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg_pending_pick_mode(),
            reply_markup=mode_keyboard(prefix="pick:")
        )
        return

    msg = format_scenario(scenario_mode, int(number))
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=action_keyboard()
    )

# ============================================================
# Stats helpers
# ============================================================
def stats_verdict_counts_all(chat_id: int | None = None):
    """
    Když chat_id je None -> globál
    Jinak -> jen pro uživatele
    """
    with db() as conn:
        if chat_id is None:
            rows = conn.execute("""
                SELECT
                    CASE WHEN verdict IS NULL THEN 'BEZ VERDIKTU' ELSE verdict END as v,
                    COUNT(*)
                FROM rolls
                GROUP BY v
                ORDER BY COUNT(*) DESC
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT
                    CASE WHEN verdict IS NULL THEN 'BEZ VERDIKTU' ELSE verdict END as v,
                    COUNT(*)
                FROM rolls
                WHERE chat_id=?
                GROUP BY v
                ORDER BY COUNT(*) DESC
            """, (chat_id,)).fetchall()
        return rows

def stats_users_count() -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def stats_totals() -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]

def stats_top_uhnul_planes(limit: int = 5, chat_id: int | None = None):
    with db() as conn:
        if chat_id is None:
            return conn.execute("""
                SELECT plane, COUNT(*) as c
                FROM rolls
                WHERE verdict='UHNUL'
                GROUP BY plane
                ORDER BY c DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return conn.execute("""
            SELECT plane, COUNT(*) as c
            FROM rolls
            WHERE chat_id=? AND verdict='UHNUL'
            GROUP BY plane
            ORDER BY c DESC
            LIMIT ?
        """, (chat_id, limit)).fetchall()

def stats_mode_rates():
    with db() as conn:
        return conn.execute("""
            SELECT scenario_mode,
                   SUM(CASE WHEN verdict='OBSTÁL' THEN 1 ELSE 0 END) as ok,
                   COUNT(*) as n
            FROM rolls
            WHERE verdict IS NOT NULL
              AND scenario_mode IS NOT NULL
              AND scenario_mode != ''
            GROUP BY scenario_mode
            ORDER BY n DESC
        """).fetchall()

def stats_streaks(chat_id: int):
    """
    - streak_obstal: kolik dní v řadě OBSTÁL
    - streak_bez_uhnul: kolik dní v řadě nebylo UHNUL (OBSTÁL nebo BEZ VERDIKTU)
      Pozn.: když dnes nemáš verdikt (NULL), streak_bez_uhnul se počítá, ale streak_obstal ne.
    """
    with db() as conn:
        rows = conn.execute("""
            SELECT verdict
            FROM rolls
            WHERE chat_id=?
            ORDER BY day DESC
        """, (chat_id,)).fetchall()

    streak_obstal = 0
    streak_bez_uhnul = 0

    for (verdict,) in rows:
        if verdict == "OBSTÁL":
            streak_obstal += 1
            streak_bez_uhnul += 1
            continue
        if verdict == "UHNUL":
            break
        # BEZ VERDIKTU (NULL)
        streak_bez_uhnul += 1
        break

    return streak_obstal, streak_bez_uhnul

# ============================================================
# Telegram handlers
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    # /start zároveň znovu zapne připomínky
    set_user_enabled(chat_id, True)

    await update.message.reply_text(start_text(), parse_mode=ParseMode.HTML)

    # reschedule, aby se nelepily staré joby
    await schedule_user_jobs(context, chat_id, force_reschedule=True)
    await update.message.reply_text("Ráno a večer přijde připomínka.\nRytmus změníš: /cas 07:00 21:00")

async def cmd_hod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /hod:
    - pokud dnes existuje a je pending -> nabídne volbu tónu
    - pokud dnes existuje a je uzamčeno -> ukáže scénář
    - pokud dnes neexistuje -> vytvoří pending a nabídne volbu tónu
    """
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    row = get_today_roll(chat_id)
    if row:
        _day, number, _plane, scenario_mode, pending, _verdict = row
        if int(pending) == 1 or not scenario_mode:
            await update.message.reply_text(msg_pending_pick_mode(), reply_markup=mode_keyboard(prefix="pick:"))
            return
        msg = format_scenario(scenario_mode, int(number))
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=action_keyboard())
        return

    number = daily_number(chat_id)
    save_pending_roll(chat_id, number)
    await update.message.reply_text(
        f"🎲 Rovina dne: <b>{number} — {h(PLANES[number])}</b>\n\n{msg_pending_pick_mode()}",
        parse_mode=ParseMode.HTML,
        reply_markup=mode_keyboard(prefix="pick:"),
    )

async def cmd_dnes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    await show_today_status(context, chat_id)

async def cmd_rezim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rezim:
    - když dnešek pending -> nabídne volbu tónu pro dnešek (uzamkne scénář)
    - jinak -> nastaví výchozí tón do budoucna
    """
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    if is_pending_today(chat_id):
        await update.message.reply_text(
            "Dnes je rovina určená. Zvol tón pro dnešek:",
            reply_markup=mode_keyboard(prefix="pick:")
        )
        return

    await update.message.reply_text("Zvol výchozí tón:", reply_markup=mode_keyboard(prefix="default:"))

async def cmd_historie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    rows = last_12(chat_id)
    if not rows:
        await update.message.reply_text("Zatím žádná stopa.")
        return

    def dot(v):
        if v == "OBSTÁL":
            return "●"
        if v == "UHNUL":
            return "○"
        return "·"  # BEZ VERDIKTU

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
        users = stats_users_count()
        total = stats_totals()
        verdicts = stats_verdict_counts_all(chat_id=None)
        top_uhnul = stats_top_uhnul_planes(limit=5, chat_id=None)
        mode_rates = stats_mode_rates()

        v_lines = [f"• {v}: {c}" for v, c in verdicts] if verdicts else ["—"]
        t_lines = [f"• {plane}: {c}" for plane, c in top_uhnul] if top_uhnul else ["—"]

        m_lines = []
        if mode_rates:
            for mode, ok, n in mode_rates:
                rate = (ok / n * 100.0) if n else 0.0
                m_lines.append(f"• {mode}: {ok}/{n} ({rate:.0f} %)")
        else:
            m_lines = ["—"]

        text = (
            "<b>/stat — Globální přehled</b>\n\n"
            f"Uživatelé: <b>{users}</b>\n"
            f"Záznamy: <b>{total}</b>\n\n"
            "<b>Verdikty</b>\n"
            + "\n".join(v_lines) +
            "\n\n<b>Nejčastější UHNUL (roviny)</b>\n"
            + "\n".join(t_lines) +
            "\n\n<b>Úspěšnost podle režimu (jen tam, kde je verdikt)</b>\n"
            + "\n".join(m_lines)
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # user stats
    verdicts = stats_verdict_counts_all(chat_id=chat_id)
    streak_obstal, streak_bez_uhnul = stats_streaks(chat_id)
    top_uhnul = stats_top_uhnul_planes(limit=5, chat_id=chat_id)

    # vytáhneme počty pro výpočet úspěšnosti
    ok_ = next((c for v, c in verdicts if v == "OBSTÁL"), 0)
    uhnul = next((c for v, c in verdicts if v == "UHNUL"), 0)
    no_v = next((c for v, c in verdicts if v == "BEZ VERDIKTU"), 0)
    total = ok_ + uhnul + no_v
    rate = (ok_ / (ok_ + uhnul) * 100.0) if (ok_ + uhnul) else 0.0

    v_lines = [f"• {v}: {c}" for v, c in verdicts] if verdicts else ["—"]
    top_lines = [f"• {plane}: {c}" for plane, c in top_uhnul] if top_uhnul else ["—"]

    text = (
        "<b>/stat — Tvoje stopa</b>\n\n"
        f"Záznamy: <b>{total}</b>\n\n"
        "<b>Verdikty</b>\n"
        + "\n".join(v_lines) +
        "\n\n<b>Úspěšnost (z verdiktů)</b>\n"
        f"• <b>{rate:.0f} %</b>\n\n"
        "<b>Streak</b>\n"
        f"• OBSTÁL v řadě: <b>{streak_obstal}</b>\n"
        f"• Bez UHNUL: <b>{streak_bez_uhnul}</b>\n\n"
        "<b>Kde nejčastěji uhýbáš</b>\n"
        + "\n".join(top_lines)
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ============================================================
# Callback handler
# ============================================================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    data = (query.data or "").strip()
    upsert_user(chat_id)

    # PŘIJÍMÁM
    if data == "accept":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Přijato.\nTeď to unes.")
        return

    # VERDIKT
    if data == "verdict":
        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text(msg_no_roll_yet())
            return

        _day, _number, _plane, scenario_mode, pending, _verdict = row
        if int(pending) == 1 or not scenario_mode:
            await query.message.reply_text("Nejdřív zvol tón pro dnešek.", reply_markup=mode_keyboard(prefix="pick:"))
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
            [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
        ])
        await query.message.reply_text(copy_evening(scenario_mode), reply_markup=kb)
        return

    # Uložení verdiktu
    if data.startswith("v:"):
        verdict = data.split(":", 1)[1]
        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text(msg_no_roll_yet())
            return

        _day, _number, _plane, scenario_mode, pending, _verdict = row
        if int(pending) == 1 or not scenario_mode:
            await query.message.reply_text("Nejdřív zvol tón pro dnešek.", reply_markup=mode_keyboard(prefix="pick:"))
            return

        set_verdict(chat_id, verdict)
        await query.message.reply_text(verdict_reply(scenario_mode, verdict))
        return

    # Volba tónu pro dnešek (uzamčení) + uložit jako výchozí
    if data.startswith("pick:"):
        mode = data.split(":", 1)[1]
        if mode not in MODES:
            return

        row = get_today_roll(chat_id)
        if not row:
            await query.message.reply_text("Nejdřív hoď: /hod")
            return

        _day, number, _plane, scenario_mode, pending, _verdict = row

        if int(pending) == 0 and scenario_mode:
            # dnešek už uzamčený -> jen nastav default do budoucna
            set_user_mode(chat_id, mode)
            await query.message.reply_text(f"Dnešek už je uzamčený.\n{msg_mode_default_set(mode)}")
            return

        finalize_roll_mode(chat_id, mode)
        set_user_mode(chat_id, mode)

        msg = format_scenario(mode, int(number))
        await query.message.reply_text(f"Režim: {mode}")
        await query.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=action_keyboard())
        return

    # Nastavení výchozího režimu do budoucna
    if data.startswith("default:"):
        mode = data.split(":", 1)[1]
        if mode not in MODES:
            return
        set_user_mode(chat_id, mode)
        await query.message.reply_text(msg_mode_default_set(mode))
        return

    # Ranní tlačítko "HOĎ"
    if data == "roll_now":
        row = get_today_roll(chat_id)
        if not row:
            number = daily_number(chat_id)
            save_pending_roll(chat_id, number)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎲 Rovina dne: <b>{number} — {h(PLANES[number])}</b>\n\n{msg_pending_pick_mode()}",
                parse_mode=ParseMode.HTML,
                reply_markup=mode_keyboard(prefix="pick:"),
            )
            return
        await show_today_status(context, chat_id)
        return

# ============================================================
# Scheduling (JobQueue)
# ============================================================
async def schedule_user_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int, force_reschedule: bool = False):
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

    if not force_reschedule and any(j.name == jname_m for j in context.job_queue.jobs()):
        return

    context.job_queue.run_daily(morning_job, time=morning_t, name=jname_m, chat_id=chat_id)
    context.job_queue.run_daily(evening_job, time=evening_t, name=jname_e, chat_id=chat_id)

async def unschedule_user_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    for j in list(context.job_queue.jobs()):
        if j.name in (f"morning:{chat_id}", f"evening:{chat_id}"):
            j.schedule_removal()

async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or int(u[4]) != 1:
        return

    default_mode = u[1]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("HOĎ", callback_data="roll_now")]])
    await context.bot.send_message(chat_id=chat_id, text=copy_morning(default_mode), reply_markup=kb)

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or int(u[4]) != 1:
        return

    row = get_today_roll(chat_id)
    if not row:
        await context.bot.send_message(chat_id=chat_id, text="Bez hodu není stopa.\nPoužij /hod.")
        return

    _day, _number, _plane, scenario_mode, pending, _verdict = row
    if int(pending) == 1 or not scenario_mode:
        await context.bot.send_message(chat_id=chat_id, text="Dnes ještě chybí tón.\nZvol ho: /rezim")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
        [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
    ])
    await context.bot.send_message(chat_id=chat_id, text=copy_evening(scenario_mode), reply_markup=kb)

# ============================================================
# Main
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

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
