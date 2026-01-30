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
    Tenhle mini-server odpoví 200 OK a udrží deploy zelený.
    """
    port = int(os.getenv("PORT", "10000"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, fmt, *args):
            return  # potlačí log spam

    httpd = socketserver.TCPServer(("", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

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
# VOICE / UX COPY (sjednoceno)
# =========================
def start_text() -> str:
    return (
        "<b>DODEKAEDR</b>\n"
        "Digitální disciplína reality.\n\n"
        "Hod určuje rovinu dne.\n"
        "Nevybíráš si ji. Přijímáš ji.\n\n"
        "<b>Příkazy</b>\n"
        "• /hod — dnešní hod (1× denně)\n"
        "• /dnes — připomene dnešní rovinu\n"
        "• /historie — posledních 12 dní\n"
        "• /rezim — zvol tón\n"
        "• /cas 07:00 21:00 — nastav rytmus\n"
        "• /stop — zastaví připomínky\n\n"
        "Začni až ve chvíli, kdy uneseš důsledek."
    )

def copy_morning(mode: str) -> str:
    if mode == "LEGIONÁŘSKÝ":
        return "Dnes se ukáže charakter.\n\n🎲 Hoď, až nebudeš vyjednávat."
    if mode == "TVRDÝ":
        return "Dnes se počítá tvar.\n\n🎲 Hoď, a drž směr."
    return "Dnes přijde rovina.\n\n🎲 Hoď, a neuhni."

def copy_evening(mode: str) -> str:
    if mode == "LEGIONÁŘSKÝ":
        return "Den je uzavřen.\n\nObstál jsi, nebo jsi uhnul?"
    if mode == "TVRDÝ":
        return "Teď bez výmluv.\n\nObstál jsi, nebo jsi uhnul?"
    return "Závěr dne.\n\nObstál jsi, nebo jsi uhnul?"

def msg_no_roll_yet() -> str:
    return "Dnes ještě nepadl hod.\nPoužij /hod."

def msg_accept_logged() -> str:
    return "Přijato.\nTeď to unes."

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

def msg_mode_set(new_mode: str) -> str:
    return f"Režim: {new_mode}"

def verdict_reply(mode: str, verdict: str) -> str:
    # méně “hodnocení”, více “stopa”
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

    # HTML-safe
    plane_h = h(plane)
    impulse_h = h(impulse)
    task_h = h(task)

    return (
        f"<b>🎲 {number} — {plane_h}</b>\n"
        f"<i>{impulse_h}</i>\n\n"
        f"<b>{task_h}</b>\n"
        f"<i>Uzamčeno do 24:00.</i>"
    )

def valid_hhmm(s: str) -> bool:
    try:
        hh, mm = s.split(":")
        h0 = int(hh); m0 = int(mm)
        return 0 <= h0 <= 23 and 0 <= m0 <= 59
    except Exception:
        return False

# =========================
# Telegram handlers
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    await update.message.reply_text(start_text(), parse_mode=ParseMode.HTML)

    await schedule_user_jobs(context, chat_id)
    await update.message.reply_text("Ráno a večer přijde připomínka.\nRytmus změníš: /cas 07:00 21:00")

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

    save_roll(chat_id, number, PLANES[number], mode)

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
        await update.message.reply_text(msg_no_roll_yet())
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

    lines = ["Posledních 12 dní:\n"]
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
    await update.message.reply_text("Zvol tón dne:", reply_markup=keyboard)

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
        await query.message.reply_text(msg_accept_logged())
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
            await query.message.reply_text(msg_no_roll_yet())
            return

        set_verdict(chat_id, verdict)
        await query.message.reply_text(verdict_reply(mode, verdict))
        return

    if data.startswith("mode:"):
        new_mode = data.split(":", 1)[1]
        if new_mode not in MODES:
            return
        set_user_mode(chat_id, new_mode)
        await query.message.reply_text(msg_mode_set(new_mode))
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
    save_roll(chat_id, number, PLANES[number], mode)

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

    if not force_reschedule:
        if any(j.name == jname_m for j in context.job_queue.jobs()):
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
    if not u or u[4] != 1:
        return
    mode = u[1]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("HOĎ", callback_data="roll_now")]])
    await context.bot.send_message(chat_id=chat_id, text=copy_morning(mode), reply_markup=kb)

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    u = get_user(chat_id)
    if not u or u[4] != 1:
        return
    mode = u[1]

    if not has_roll_for_today(chat_id):
        await context.bot.send_message(chat_id=chat_id, text="Bez hodu není stopa.\nPoužij /hod.")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("OBSTÁL JSEM", callback_data="v:OBSTÁL")],
        [InlineKeyboardButton("UHNUL JSEM", callback_data="v:UHNUL")],
    ])
    await context.bot.send_message(chat_id=chat_id, text=copy_evening(mode), reply_markup=kb)

# =========================
# Main
# =========================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Chybí BOT_TOKEN (nastav jako env proměnnou).")

    start_health_server()  # Render Web Service: bind to PORT
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

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
