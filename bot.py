import os
import sqlite3
import threading
import http.server
import socketserver
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# =========================
# CONFIG
# =========================
TZ = ZoneInfo("Europe/Prague")
DB_PATH = os.getenv("DB_PATH", "/var/data/dodekaedr.db")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

MORNING_DEFAULT = "07:00"
EVENING_DEFAULT = "21:00"

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

# =========================
# Render health server (PORT binding)
# =========================
def start_health_server():
    """
    Render Web Service vyžaduje otevřený port (PORT).
    Tento mini-server odpoví 200 OK.
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
    logging.info("Health server running on port %s", port)

# =========================
# DB
# =========================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rolls (
                chat_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                number INTEGER NOT NULL,
                plane TEXT NOT NULL,
                mode TEXT NOT NULL,
                verdict TEXT DEFAULT NULL,
                rolled_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, day)
            )
        """)

def upsert_user(chat_id: int):
    with db() as conn:
        conn.execute("""
            INSERT INTO users (chat_id) VALUES (?)
            ON CONFLICT(chat_id) DO NOTHING
        """, (chat_id,))

def get_user(chat_id: int):
    with db() as conn:
        cur = conn.execute(
            "SELECT chat_id, mode, morning_time, evening_time, is_enabled FROM users WHERE chat_id=?",
            (chat_id,),
        )
        return cur.fetchone()

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

def has_roll_for_today(chat_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("SELECT 1 FROM rolls WHERE chat_id=? AND day=?", (chat_id, today_str()))
        return cur.fetchone() is not None

def get_today_roll(chat_id: int):
    with db() as conn:
        cur = conn.execute(
            "SELECT day, number, plane, mode, verdict FROM rolls WHERE chat_id=? AND day=?",
            (chat_id, today_str()),
        )
        return cur.fetchone()

def save_roll(chat_id: int, number: int, plane: str, mode: str):
    with db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO rolls (chat_id, day, number, plane, mode, verdict, rolled_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
        """, (chat_id, today_str(), number, plane, mode, now_iso()))

def set_verdict(chat_id: int, verdict: str):
    with db() as conn:
        conn.execute("UPDATE rolls SET verdict=? WHERE chat_id=? AND day=?", (verdict, chat_id, today_str()))

def last_12(chat_id: int):
    with db() as conn:
        cur = conn.execute("""
            SELECT day, number, plane, verdict
            FROM rolls
            WHERE chat_id=?
            ORDER BY day DESC
            LIMIT 12
        """, (chat_id,))
        return cur.fetchall()

# =========================
# UX COPY
# =========================
def copy_morning(mode: str) -> str:
    if mode == "LEGIONÁŘSKÝ":
        return "Dnes se ukáže charakter.\n\n🎲 Hoď kostkou."
    if mode == "TVRDÝ":
        return "Dnes čeká rozhodnutí.\n\n🎲 Hoď kostkou."
    return "Dnes čeká nová rovina.\n\n🎲 Hoď kostkou."

def copy_evening(mode: str) -> str:
    if mode == "LEGIONÁŘSKÝ":
        return "Verdikt. Teď.\n\nObstál jsi — nebo jsi uhnul?"
    if mode == "TVRDÝ":
        return "Čas říct pravdu.\n\nObstál jsi — nebo jsi uhnul?"
    return "Nastal čas verdiktu.\n\nObstál jsi — nebo jsi uhnul?"

def format_scenario(mode: str, number: int) -> str:
    plane = PLANES[number]
    impulse, task = SCENARIOS[mode][number]
    return (
        f"<b>🎲 {number} — {plane}</b>\n"
        f"Impuls: <i>{impulse}</i>\n"
        f"Scénář: <b>{task}</b>\n"
        f"Stav: <i>Uzamčeno do 24:00.</i>"
    )

def valid_hhmm(s: str) -> bool:
    try:
        hh, mm = s.split(":")
        h = int(hh); m = int(mm)
        return 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return False

# =========================
# Telegram handlers
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    text = (
        "DODEKAEDR — digitální disciplína reality\n\n"
        "Princip: Hoď. Přijmi. Neuhýbej.\n\n"
        "Příkazy:\n"
        "/hod — hod kostkou (1× denně)\n"
        "/dnes — dnešní scénář\n"
        "/historie — posledních 12 dní\n"
        "/rezim — změna tónu\n"
        "/cas 07:00 21:00 — nastavení ráno/večer\n"
        "/stop — pozastavit\n"
    )
    await update.message.reply_text(text)

    await schedule_user_jobs(context, chat_id)
    await update.message.reply_text("Ráno a večer ti připomenu rituál. Časy změníš: /cas 07:00 21:00")

async def cmd_hod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    u = get_user(chat_id)
    mode = u[1]

    if has_roll_for_today(chat_id):
        row = get_today_roll(chat_id)
        number = row[1]
        msg = format_scenario(mode, number)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    seed = int(datetime.now(TZ).strftime("%Y%m%d")) + chat_id
    number = (seed % 12) + 1

    plane = PLANES[number]
    save_roll(chat_id, number, plane, mode)

    msg = format_scenario(mode, number)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("PŘIJÍMÁM", callback_data="accept")],
        [InlineKeyboardButton("VERDIKT", callback_data="verdict")],
    ])
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def cmd_dnes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    u = get_user(chat_id)
    mode = u[1]

    row = get_today_roll(chat_id)
    if not row:
        await update.message.reply_text("Dnes ještě nebyl hod. Použij: /hod")
        return

    number = row[1]
    msg = format_scenario(mode, number)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

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

    lines = ["Historie (posledních 12 dní):\n"]
    for d, num, plane, verdict in rows:
        lines.append(f"{dot(verdict)}  {d} — {num} {plane}")
    await update.message.reply_text("\n".join(lines))

async def cmd_rezim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ZÁKLADNÍ", callback_data="mode:ZÁKLADNÍ")],
        [InlineKeyboardButton("TVRDÝ", callback_data="mode:TVRDÝ")],
        [InlineKeyboardButton("LEGIONÁŘSKÝ", callback_data="mode:LEGIONÁŘSKÝ")],
    ])
    await update.message.reply_text("Zvol režim:", reply_markup=keyboard)

async def cmd_cas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    parts = (update.message.text or "").strip().split()
    if len(parts) == 1:
        msg = (
            "Nastavení času (formát HH:MM)\n"
            "Použij:\n"
            "/cas 07:00 21:00\n\n"
            "První čas = ráno, druhý = večer."
        )
        await update.message.reply_text(msg)
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
    await update.message.reply_text(f"Nastaveno. Ráno: {morning}, večer: {evening}")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)
    set_user_enabled(chat_id, False)
    await unschedule_user_jobs(context, chat_id)
    await update.message.reply_text("Pozastaveno. Pokud chceš znovu: /start")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    data = query.data or ""
    upsert_user(chat_id)
    u = get_user(chat_id)
    mode = u[1]

    if data == "accept":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Zaznamenáno. Pokračuj.")
        return

    if data == "verdict":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
            [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
        ])
        await query.message.reply_text(copy_evening(mode), reply_markup=kb)
        return

    if data.startswith("v:"):
        verdict = data.split(":", 1)[1]
        if not has_roll_for_today(chat_id):
            await query.message.reply_text("Dnes ještě nebyl hod. /hod")
            return

        set_verdict(chat_id, verdict)
        if verdict == "OBSTÁL":
            text = "Charakter obstál." if mode == "LEGIONÁŘSKÝ" else ("Udržel jsi strukturu." if mode == "TVRDÝ" else "Zůstáváš ve tvaru.")
        else:
            text = "Selhání zaznamenáno." if mode == "LEGIONÁŘSKÝ" else ("Pravda zaznamenána." if mode == "TVRDÝ" else "Zaznamenáno. Pokračuj.")
        await query.message.reply_text(text)
        return

    if data.startswith("mode:"):
        new_mode = data.split(":", 1)[1]
        if new_mode not in MODES:
            return
        set_user_mode(chat_id, new_mode)
        await query.message.reply_text(f"Režim nastaven: {new_mode}")
        return

async def on_roll_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat.id
    upsert_user(chat_id)
    u = get_user(chat_id)
    mode = u[1]

    if has_roll_for_today(chat_id):
        row = get_today_roll(chat_id)
        number = row[1]
        msg = format_scenario(mode, number)
        await query.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    seed = int(datetime.now(TZ).strftime("%Y%m%d")) + chat_id
    number = (seed % 12) + 1
    plane = PLANES[number]
    save_roll(chat_id, number, plane, mode)

    msg = format_scenario(mode, number)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("PŘIJÍMÁM", callback_data="accept")],
        [InlineKeyboardButton("VERDIKT", callback_data="verdict")],
    ])
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# =========================
# Scheduling (JobQueue)
# =========================
async def schedule_user_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int, force_reschedule: bool = False):
    if force_reschedule:
        await unschedule_user_jobs(context, chat_id)

    u = get_user(chat_id)
    if not u or u[4] != 1:
        return

    morning_str = u[2] or MORNING_DEFAULT
    evening_str = u[3] or EVENING_DEFAULT

    morning_t = time(int(morning_str.split(":")[0]), int(morning_str.split(":")[1]), tzinfo=TZ)
    evening_t = time(int(evening_str.split(":")[0]), int(evening_str.split(":")[1]), tzinfo=TZ)

    jname_m = f"morning:{chat_id}"
    jname_e = f"evening:{chat_id}"

    existing = {j.name for j in context.job_queue.jobs()}
    has_m = jname_m in existing
    has_e = jname_e in existing

    if not force_reschedule and has_m and has_e:
        return

    if not has_m:
        context.job_queue.run_daily(morning_job, time=morning_t, name=jname_m, chat_id=chat_id)
    if not has_e:
        context.job_queue.run_daily(evening_job, time=evening_t, name=jname_e, chat_id=chat_id)

async def unschedule_user_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    for j in list(context.job_queue.jobs()):
        if j.name in (f"morning:{chat_id}", f"evening:{chat_id}"):
            j.schedule_removal()

async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or u[4] != 1:
        return
    mode = u[1]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("HOĎ KOSTKOU", callback_data="roll_now")]])
    await context.bot.send_message(chat_id=chat_id, text=copy_morning(mode), reply_markup=kb)

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or u[4] != 1:
        return
    mode = u[1]

    if not has_roll_for_today(chat_id):
        await context.bot.send_message(chat_id=chat_id, text="Dnes ještě nebyl hod. /hod")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
        [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
    ])
    await context.bot.send_message(chat_id=chat_id, text=copy_evening(mode), reply_markup=kb)

# =========================
# App lifecycle hooks
# =========================
async def post_init(app: Application):
    me = await app.bot.get_me()
    logging.info("✅ Bot připojen: @%s (id=%s)", me.username, me.id)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("❌ Exception", exc_info=context.error)

# =========================
# Main
# =========================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Chybí BOT_TOKEN (nastav jako env proměnnou).")

    # ensure DB directory exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Render Web Service needs PORT bound
    start_health_server()

    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hod", cmd_hod))
    app.add_handler(CommandHandler("dnes", cmd_dnes))
    app.add_handler(CommandHandler("historie", cmd_historie))
    app.add_handler(CommandHandler("rezim", cmd_rezim))
    app.add_handler(CommandHandler("cas", cmd_cas))
    app.add_handler(CommandHandler("stop", cmd_stop))

    app.add_handler(CallbackQueryHandler(on_roll_now_callback, pattern="^roll_now$"))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
