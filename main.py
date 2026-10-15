import asyncio
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- PYTHON EVENT LOOP FIX ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# --- DUMMY WEB SERVER FOR RENDER (24/7 ONLINE) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot status: Online and Operational.")

    def log_message(self, format, *args):
        return

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_dummy_server, daemon=True).start()

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatPrivileges, ChatPermissions, ChatMemberUpdated, CallbackQuery
from pyrogram.errors import RPCError
from pyrogram.raw import functions

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "123456789"))

app = Client("advanced_guard_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- OWNER INTERACTIVE STATES STORAGE ---
owner_states = {}

# --- HELPER FOR GLOBAL BUTTON ---
def get_protect_btn(client: Client):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Protect your group 🛡", url=f"https://t.me/{client.me.username}?startgroup=true")]
    ])

# --- HELPER FOR OWNER PANEL BUTTONS ---
def get_owner_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Managed Groups & Links", callback_data="owner_groups")],
        [InlineKeyboardButton("👑 Promote Admin in Group", callback_data="owner_promote_select")],
        [InlineKeyboardButton("🚀 Broadcast Message", callback_data="owner_broadcast_prompt")]
    ])

# --- HELPER FOR FORMATTING WARNING / ACTION MESSAGES ---
def format_alert_text(header_title: str, user, reason: str, warn_count=None):
    text = f"{header_title}\n\n"
    text += f"👤 **User -** {user.mention}\n"
    text += f"🆔 **Id -** `{user.id}`\n"
    text += f"📝 **Reason -** {reason}\n"
    if warn_count is not None:
        text += f"⚠️ **Warn Count -** `{warn_count}/3`\n"
    return text

# --- DATABASE SETUP ---
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    username TEXT,
    autodelete_sec INTEGER DEFAULT 0,
    forward_protect INTEGER DEFAULT 1,
    nolinks INTEGER DEFAULT 1,
    profanity_filter INTEGER DEFAULT 1,
    bio_scanner INTEGER DEFAULT 1,
    antispam INTEGER DEFAULT 0,
    antispam_mode INTEGER DEFAULT 0,
    imagefilter INTEGER DEFAULT 1,
    noevents INTEGER DEFAULT 0,
    nolocations INTEGER DEFAULT 1,
    nocontacts INTEGER DEFAULT 1,
    nocommands INTEGER DEFAULT 0,
    nohashtags INTEGER DEFAULT 1,
    novoice INTEGER DEFAULT 0,
    nobots INTEGER DEFAULT 1,
    antiflood INTEGER DEFAULT 0,
    welcome INTEGER DEFAULT 0
)
""")

db_columns = [
    "forward_protect INTEGER DEFAULT 1",
    "nolinks INTEGER DEFAULT 1",
    "profanity_filter INTEGER DEFAULT 1",
    "bio_scanner INTEGER DEFAULT 1",
    "antispam INTEGER DEFAULT 0",
    "antispam_mode INTEGER DEFAULT 0",
    "imagefilter INTEGER DEFAULT 1",
    "noevents INTEGER DEFAULT 0",
    "nolocations INTEGER DEFAULT 1",
    "nocontacts INTEGER DEFAULT 1",
    "nocommands INTEGER DEFAULT 0",
    "nohashtags INTEGER DEFAULT 1",
    "novoice INTEGER DEFAULT 0",
    "nobots INTEGER DEFAULT 1",
    "antiflood INTEGER DEFAULT 0",
    "welcome INTEGER DEFAULT 0"
]

for col_def in db_columns:
    try:
        cursor.execute(f"ALTER TABLE groups ADD COLUMN {col_def}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS badwords (
    chat_id INTEGER,
    word TEXT,
    PRIMARY KEY (chat_id, word)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    warn_count INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")
conn.commit()

DEFAULT_BAD_WORDS = [
    "gali", "mc", "bc", "bhenchod", "madarchod", "chutiya", "gaand", "bhosdike",
    "harami", "laude", "lodu", "randi", "saale", "fuck", "bitch", "bastard", "asshole"
]

LINK_PATTERN = re.compile(r'(https?://|t\.me/|telegram\.me/|telegram\.dog/|@[a-zA-Z0-9_]{4,})', re.IGNORECASE)

def parse_target(input_str: str):
    input_str = input_str.strip()
    c_match = re.search(r't\.me/c/(\d+)', input_str)
    if c_match:
        return int(f"-100{c_match.group(1)}")
    u_match = re.search(r'(?:t\.me/|@)([a-zA-Z0-9_]{4,})', input_str)
    if u_match:
        return f"@{u_match.group(1)}"
    if input_str.lstrip('-').isdigit():
        return int(input_str)
    return input_str

def save_or_update_group(chat_id, title, username):
    cursor.execute("""
    INSERT INTO groups (chat_id, title, username) VALUES (?, ?, ?)
    ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username
    """, (chat_id, title, username))
    conn.commit()

def get_group_settings(chat_id):
    cursor.execute("""
    SELECT autodelete_sec, forward_protect, nolinks, profanity_filter, bio_scanner,
           antispam, antispam_mode, imagefilter, noevents, nolocations, nocontacts,
           nocommands, nohashtags, novoice, nobots, antiflood, welcome
    FROM groups WHERE chat_id = ?
    """, (chat_id,))
    res = cursor.fetchone()
    if not res:
        return {
            "autodelete_sec": 0, "forward_protect": 1, "nolinks": 1, "profanity_filter": 1,
            "bio_scanner": 1, "antispam": 0, "antispam_mode": 0, "imagefilter": 1,
            "noevents": 0, "nolocations": 1, "nocontacts": 1, "nocommands": 0,
            "nohashtags": 1, "novoice": 0, "nobots": 1, "antiflood": 0, "welcome": 0
        }
    keys = [
        "autodelete_sec", "forward_protect", "nolinks", "profanity_filter", "bio_scanner",
        "antispam", "antispam_mode", "imagefilter", "noevents", "nolocations", "nocontacts",
        "nocommands", "nohashtags", "novoice", "nobots", "antiflood", "welcome"
    ]
    return dict(zip(keys, res))

def update_group_setting(chat_id, column, value):
    cursor.execute(f"UPDATE groups SET {column} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()

def get_all_groups_details():
    cursor.execute("SELECT chat_id, title, username FROM groups")
    return cursor.fetchall()

def get_warns(chat_id, user_id):
    cursor.execute("SELECT warn_count FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    res = cursor.fetchone()
    return res[0] if res else 0

def add_warn(chat_id, user_id):
    current = get_warns(chat_id, user_id) + 1
    cursor.execute("INSERT OR REPLACE INTO warnings (chat_id, user_id, warn_count) VALUES (?, ?, ?)", (chat_id, user_id, current))
    conn.commit()
    return current

def reset_warns(chat_id, user_id):
    cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    conn.commit()

def get_group_bad_words(chat_id):
    cursor.execute("SELECT word FROM badwords WHERE chat_id = ?", (chat_id,))
    custom = [row[0] for row in cursor.fetchall()]
    return list(set(DEFAULT_BAD_WORDS + custom))

async def delete_after_delay(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

@app.on_my_chat_member()
async def track_bot_chats(client: Client, update: ChatMemberUpdated):
    chat = update.chat
    if update.new_chat_member:
        status = update.new_chat_member.status
        st_val = status.value if hasattr(status, "value") else str(status)
        if st_val in ["member", "administrator"]:
            save_or_update_group(chat.id, chat.title, chat.username)
        elif st_val in ["left", "banned"]:
            cursor.execute("DELETE FROM groups WHERE chat_id = ?", (chat.id,))
            conn.commit()

async def check_bot_admin_rights(client: Client, chat_id: int):
    try:
        member = await client.get_chat_member(chat_id, "me")
        if member.status.value != "administrator":
            return False, "Not an Administrator"
        
        priv = member.privileges
        if not priv or not (priv.can_delete_messages and priv.can_restrict_members):
            return False, "Missing Delete Messages or Ban Users permission"
            
        return True, "Full Access"
    except Exception as e:
        return False, str(e)

async def process_violation(client: Client, message: Message, user, reason: str, header: str):
    chat_id = message.chat.id
    try:
        await message.delete()
    except Exception:
        pass

    warn_count = add_warn(chat_id, user.id)

    if warn_count < 3:
        alert_text = format_alert_text(header, user, reason, warn_count)
        await message.reply_text(alert_text, reply_markup=get_protect_btn(client))
    else:
        try:
            until_time = datetime.now() + timedelta(hours=1)
            await client.restrict_chat_member(chat_id, user.id, ChatPermissions(), until_date=until_time)
        except Exception as e:
            print(f"Failed to mute user: {e}")

        reset_warns(chat_id, user.id)
        alert_text = format_alert_text("🔇 **User Auto-Muted (1 Hour)**", user, f"Reached 3/3 warnings ({reason})", 3)
        await message.reply_text(alert_text, reply_markup=get_protect_btn(client))

@app.on_message(filters.command(["start", "help"]))
async def start_command(client: Client, message: Message):
    if message.from_user and message.from_user.id == OWNER_ID and message.chat.type.value == "private":
        panel_text = (
            f"👑 **Welcome Owner!**\n\n"
            f"Yeh aapka advanced bot management dashboard hai. Niche diye gaye buttons se aap apne groups dekh sakte hain, admin promote kar sakte hain, ya broadcast bhej sakte hain."
        )
        return await message.reply_text(panel_text, reply_markup=get_owner_panel_keyboard())

    protect_btn = get_protect_btn(client)
    bot_username = client.me.username

    start_text = (
        f"Blacklist words and domains; remove profanity and flood messages; "
        f"restrict permissions for spammers; stop members from adding spam bots to your group.\n\n"
        f"**How to start using bot?**\n"
        f"1) Add @{bot_username} to your group.\n"
        f"2) Assign admin permissions (delete messages, ban users).\n"
        f"3) Run /start command in the group.\n"
        f"4) Change settings using /status."
    )
    await message.reply_text(start_text, reply_markup=protect_btn, disable_web_page_preview=True)

@app.on_callback_query(filters.user(OWNER_ID))
async def owner_panel_callbacks(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    
    if data == "owner_groups":
        groups = get_all_groups_details()
        if not groups:
            return await callback_query.answer("No registered groups found!", show_alert=True)

        out = "📋 **Managed Network Groups & Links**\n───•────────────────•───\n\n"
        for chat_id, title, username in groups:
            if username:
                link = f"https://t.me/{username}"
            else:
                chat_str = str(chat_id)
                if chat_str.startswith("-100"):
                    link = f"https://t.me/c/{chat_str[4:]}/1"
                elif chat_str.startswith("-"):
                    link = f"https://t.me/c/{chat_str[1:]}/1"
                else:
                    link = f"https://t.me/{chat_id}"

            out += f"• **{title or 'Group'}**\n   🔗 {link}\n\n"

        out += f"📊 **Total Groups:** `{len(groups)}`"
        await callback_query.message.edit_text(out[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Panel", callback_data="owner_back")]]), disable_web_page_preview=True)
        await callback_query.answer()

    elif data == "owner_promote_select":
        groups = get_all_groups_details()
        if not groups:
            return await callback_query.answer("No groups found where bot is active!", show_alert=True)

        buttons = []
        for chat_id, title, _ in groups:
            buttons.append([InlineKeyboardButton(f"👥 {title or 'Group'}", callback_data=f"sel_grp_{chat_id}")])
        buttons.append([InlineKeyboardButton("« Back to Panel", callback_data="owner_back")])

        await callback_query.message.edit_text("👑 **Select the group where you want to promote an admin:**", reply_markup=InlineKeyboardMarkup(buttons))
        await callback_query.answer()

    elif data.startswith("sel_grp_"):
        chat_id = int(data.split("_")[2])
        owner_states[callback_query.from_user.id] = {"action": "promote_user", "chat_id": chat_id}
        await callback_query.message.edit_text(
            "👤 **Group Selected!**\n\nAb aap mujhe us user ka **Username** (jaise `@username`) ya **User ID** bhejiye jise aap is group me admin banana chahte hain.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="owner_back")]])
        )
        await callback_query.answer()

    elif data == "owner_broadcast_prompt":
        owner_states[callback_query.from_user.id] = {"action": "broadcast_msg"}
        await callback_query.message.edit_text(
            "🚀 **Broadcast Mode Activated**\n\nAb aap jo bhi message yahan **bhejenge** ya **reply karenge**, woh sabhi groups me broadcast ho jayega.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="owner_back")]])
        )
        await callback_query.answer()

    elif data == "owner_back":
        if callback_query.from_user.id in owner_states:
            del owner_states[callback_query.from_user.id]
        await callback_query.message.edit_text("👑 **Owner Control Panel**\n\nChoose an action below:", reply_markup=get_owner_panel_keyboard())
        await callback_query.answer()

@app.on_message(filters.user(OWNER_ID) & filters.private & ~filters.command(["start", "help"]))
async def handle_owner_interactive_input(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in owner_states:
        return

    state = owner_states[user_id]
    action = state.get("action")

    if action == "promote_user":
        chat_id = state["chat_id"]
        target_input = message.text.strip()
        
        status_msg = await message.reply_text("🔄 Processing promotion...")
        try:
            target_user = await client.get_users(parse_target(target_input))
            chat = await client.get_chat(chat_id)

            await client.promote_chat_member(
                chat_id=chat.id,
                user_id=target_user.id,
                privileges=ChatPrivileges(
                    can_change_info=True,
                    can_delete_messages=True,
                    can_restrict_members=True,
                    can_invite_users=True,
                    can_pin_messages=True,
                    can_manage_video_chats=True,
                    can_promote_members=False
                )
            )
            del owner_states[user_id]
            await status_msg.edit_text(
                f"✅ **Successfully Promoted {target_user.mention} as Admin in {chat.title}!**",
                reply_markup=get_owner_panel_keyboard()
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to promote: `{e}`\n\nPlease try again or click cancel.", reply_markup=get_owner_panel_keyboard())

    elif action == "broadcast_msg":
        groups = get_all_groups_details()
        success, failed = 0, 0
        status = await message.reply_text("🚀 Broadcasting message to all groups...")

        for chat_id, _, _ in groups:
            try:
                if message.reply_to_message:
                    await message.reply_to_message.copy(chat_id)
                else:
                    await client.send_message(chat_id, message.text)
                success += 1
                await asyncio.sleep(0.5)
            except Exception:
                failed += 1

        del owner_states[user_id]
        await status.edit_text(
            f"📢 **Broadcast Finished Successfully!**\n\n✅ Delivered: `{success}` | ❌ Failed: `{failed}`",
            reply_markup=get_owner_panel_keyboard()
        )

@app.on_message(filters.group & filters.command("status"))
async def group_status(client: Client, message: Message):
    protect_btn = get_protect_btn(client)
    chat_id = message.chat.id
    user_name = message.from_user.first_name if message.from_user else "User"

    member = await client.get_chat_member(chat_id, message.from_user.id)
    if member.status.value not in ["administrator", "owner"] and message.from_user.id != OWNER_ID:
        return await message.reply_text("❌ This command is restricted to Group Admins.", reply_markup=protect_btn)

    save_or_update_group(chat_id, message.chat.title, message.chat.username)
    is_ok, reason = await check_bot_admin_rights(client, chat_id)
    s = get_group_settings(chat_id)

    admin_icon = "✅" if is_ok else "❌"
    del_icon = "✅" if is_ok else "❌"
    ban_icon = "✅" if is_ok else "❌"

    def icon(val):
        return "✅" if val == 1 else "⬜"

    status_text = (
        f"👑 **{user_name}**, bot status:\n"
        f"{admin_icon} Administrator\n"
        f"{del_icon} Can delete messages\n"
        f"{ban_icon} Can restrict members\n\n"
        f"**Filters:**\n"
        f"{icon(s['antispam'])} Antispam filter `/antispam`\n"
        f"{icon(s['imagefilter'])} Unsafe image filter `/imagefilter`\n"
        f"{icon(s['noevents'])} Join and left filter `/noevents`\n"
        f"{icon(s['nolinks'])} Links filter `/nolinks`\n"
        f"{icon(s['forward_protect'])} Forwards filter `/noforwards`\n"
        f"{icon(s['profanity_filter'])} Bad words filter `/profanity`\n"
        f"{icon(s['bio_scanner'])} Bio & Profile scanner `/bioscanner`\n"
        f"{icon(s['nobots'])} Adding spambots protection `/nobots`\n"
    )
    await message.reply_text(status_text, reply_markup=protect_btn)

@app.on_message(filters.group & ~filters.service)
async def handle_group_message(client: Client, message: Message):
    chat_id = message.chat.id
    user = message.from_user
    
    if not user or user.is_bot:
        return

    protect_btn = get_protect_btn(client)
    save_or_update_group(chat_id, message.chat.title, message.chat.username)

    is_bot_admin, err_msg = await check_bot_admin_rights(client, chat_id)
    if not is_bot_admin:
        if message.text and message.text.startswith("/"):
            await message.reply_text(
                "⚠ **Admin Rights Required!**\n> Promote bot to Admin with **Delete Messages** and **Ban Users** permissions.",
                reply_markup=protect_btn
            )
        return

    try:
        member = await client.get_chat_member(chat_id, user.id)
        is_admin = member.status.value in ["administrator", "owner"]
    except Exception:
        is_admin = False

    if is_admin or user.id == OWNER_ID:
        return

    settings = get_group_settings(chat_id)

    is_forwarded = bool(message.forward_date or message.forward_from or message.forward_from_chat or message.forward_sender_name)
    if settings["forward_protect"] == 1 and is_forwarded:
        return await process_violation(client, message, user, "Forwarding messages is strictly restricted", "⏩ **Forward Message Removed**")

    if settings["imagefilter"] == 1 and message.photo:
        return await process_violation(client, message, user, "Sending images is forbidden", "🖼️ **Image Removed**")

    if settings["profanity_filter"] == 1 and message.text:
        text_lower = message.text.lower()
        bad_words_list = get_group_bad_words(chat_id)
        has_bad_word = any(re.search(rf'\b{re.escape(w)}\b', text_lower) for w in bad_words_list)
        if has_bad_word:
            return await process_violation(client, message, user, "Using abusive language or bad words", "🤬 **Bad Words Detected**")

    if settings["nolinks"] == 1 and message.text and LINK_PATTERN.search(message.text):
        return await process_violation(client, message, user, "Posting promotional links is forbidden", "🔗 **Link Removed**")

    del_sec = settings["autodelete_sec"]
    if del_sec > 0:
        asyncio.create_task(delete_after_delay(chat_id, message.id, del_sec))

if __name__ == "__main__":
    print("Advanced Protection Bot starting successfully...")
    app.run()
