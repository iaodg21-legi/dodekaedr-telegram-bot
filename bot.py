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
DB_PATH = os.getenv("DB_PATH", "/var/data/dodekaedr.db")

ADMIN_USERNAME = "stangzk"   # bez @

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
        12: ("Ticho je také čin.", "Jednou dnes jen poslouchej."),
    },
    "TVRDÝ": {
        1: ("Tělo je základ.", "Udělej dnes něco nepohodlného pro tělo."),
        2: ("Návyk je řetěz.", "Zruš jeden zbytečný automatismus."),
        3: ("Stabilita je disciplína.", "Udrž klid pod tlakem."),
        4: ("Čin rozhoduje.", "Dokonči jednu odkládanou věc."),
        5: ("Bez směru se ztrácíš.", "Pojmenuj dnešní směr."),
        6: ("Komfort není argument.", "Udělej krok navzdory odporu."),
        7: ("Pocit není důkaz.", "Odděl fakta od interpretací."),
        8: ("Hranice chrání tvar.", "Jednou dnes odmítni."),
        9: ("Odpovědnost se neptá.", "Vezmi důsledek."),
        10: ("Paměť drží identitu.", "Vrať si jednu lekci."),
        11: ("Dopad se počítá.", "Jednej tak, aby to unesl i druhý."),
        12: ("Ticho je síla.", "Mlč a vnímej."),
    },
    "LEGIONÁŘSKÝ": {
        1: ("Tělo je bojiště.", "Bez výmluv posílíš tělo."),
        2: ("Návyk je osud.", "Zlomíš jeden špatný návyk."),
        3: ("Stabilita pod tlakem.", "Nezlomíš se."),
        4: ("Čin bez řečí.", "Uděláš to dnes."),
        5: ("Směr je závazek.", "Řekneš kam jdeš."),
        6: ("Strach není omluva.", "Uděláš krok."),
        7: ("Rozlišuj.", "Oddělíš fakt od projekce."),
        8: ("Hranice.", "Řekneš dost."),
        9: ("Odpovědnost.", "Vezmeš důsledek."),
        10: ("Paměť.", "Nezradíš lekci."),
        11: ("Propojení.", "Uvědomíš si dopad."),
        12: ("Ticho.", "Budeš poslouchat."),
    },
}

# ============================================================
# HEALTH SERVER (Render/Railway)
# ============================================================
def start_health_server():
    port = int(os.getenv("PORT", "10000"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args): pass

    httpd = socketserver.TCPServer(("", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

# ============================================================
# DB
# ============================================================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                mode TEXT DEFAULT 'ZÁKLADNÍ'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS rolls (
                chat_id INTEGER,
                day TEXT,
                number INTEGER,
                plane TEXT,
                mode TEXT,
                verdict TEXT,
                PRIMARY KEY(chat_id, day)
            )
        """)

def today():
    return datetime.now(TZ).date().isoformat()

def daily_number(chat_id: int):
    seed = int(datetime.now(TZ).strftime("%Y%m%d")) + chat_id
    return (seed % 12) + 1

# ============================================================
# CORE COMMANDS
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>DODEKAEDR</b>\nDigitální disciplína reality.\n\nPoužij /hod",
        parse_mode=ParseMode.HTML
    )

async def cmd_hod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    num = daily_number(chat_id)
    plane = PLANES[num]

    with db() as c:
        c.execute("""
            INSERT OR IGNORE INTO rolls (chat_id, day, number, plane)
            VALUES (?, ?, ?, ?)
        """, (chat_id, today(), num, plane))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ZÁKLADNÍ", callback_data="mode:ZÁKLADNÍ")],
        [InlineKeyboardButton("TVRDÝ", callback_data="mode:TVRDÝ")],
        [InlineKeyboardButton("LEGIONÁŘSKÝ", callback_data="mode:LEGIONÁŘSKÝ")],
    ])

    await update.message.reply_text(
        f"🎲 <b>{num} — {plane}</b>\n\nZvol tón dne:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id

    if q.data.startswith("mode:"):
        mode = q.data.split(":")[1]

        with db() as c:
            c.execute("UPDATE rolls SET mode=? WHERE chat_id=? AND day=?",
                      (mode, chat_id, today()))

        num, = c.execute(
            "SELECT number FROM rolls WHERE chat_id=? AND day=?",
            (chat_id, today())
        ).fetchone()

        impulse, task = SCENARIOS[mode][num]

        await q.message.reply_text(
            f"<b>{impulse}</b>\n\n{task}\n\n<i>Uzamčeno do 24:00.</i>",
            parse_mode=ParseMode.HTML
        )

# ============================================================
# MAIN
# ============================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Chybí BOT_TOKEN")

    start_health_server()
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hod", cmd_hod))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling()

if __name__ == "__main__":
    main()
