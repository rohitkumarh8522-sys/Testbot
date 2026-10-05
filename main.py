import asyncio
import re
import sqlite3

# Python 3.10+ / Render Asyncio Fix (Pyrogram import se pehle loop prepare kar rahe hain)
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# ================= CONFIGURATION =================
API_ID = 12345678          # my.telegram.org se prapt karein (Numeric Value)
API_HASH = "YOUR_API_HASH"  # my.telegram.org se prapt karein
BOT_TOKEN = "YOUR_BOT_TOKEN" # @BotFather se prapt karein
OWNER_ID = 123456789       # Apna numeric Telegram User ID yahan dalein

# Auto Delete Time (Seconds me). Example: 60 = 1 minute, 300 = 5 minutes
AUTO_DELETE_TIME = 60  
# =================================================

# Database Setup (Groups track karne ke liye)
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY)")
conn.commit()

def add_group(chat_id):
    cursor.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()

def remove_group(chat_id):
    cursor.execute("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
    conn.commit()

def get_all_groups():
    cursor.execute("SELECT chat_id FROM groups")
    return [row[0] for row in cursor.fetchall()]

app = Client("BioProtectBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Regex Pattern (Links aur @channel usernames detect karne ke liye)
LINK_PATTERN = re.compile(
    r'(https?://\S+|t\.me/\S+|telegram\.me/\S+|@[a-zA-Z0-9_]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    re.IGNORECASE
)

# --- 1. GROUP MESSAGE HANDLER (BIO CHECK & AUTO DELETE) ---
@app.on_message(filters.group)
async def group_handler(client: Client, message: Message):
    chat_id = message.chat.id
    add_group(chat_id)
    
    user = message.from_user
    if not user:
        return

    # Owner ko bypass karega (Owner ban nahi hoga)
    if user.id == OWNER_ID:
        if AUTO_DELETE_TIME > 0:
            asyncio.create_task(delete_after_delay(message, AUTO_DELETE_TIME))
        return

    # A. BIO LINK & CHANNEL CHECK
    try:
        user_chat = await client.get_chat(user.id)
        user_bio = user_chat.bio or ""
        
        # Agar bio me Link ya Channel handle (@) milta hai
        if LINK_PATTERN.search(user_bio):
            await client.ban_chat_member(chat_id, user.id)
            ban_msg = await message.reply_text(
                f"⛔ **User Banned!**\n\n"
                f"**User:** {user.mention}\n"
                f"**Reason:** Bio me Promo Link / Channel paya gaya."
            )
            await message.delete()  # User ka message delete kar do
            asyncio.create_task(delete_after_delay(ban_msg, 10)) # Warning msg 10 sec me delete
            return
    except Exception as e:
        print(f"Error checking bio: {e}")

    # B. AUTO MESSAGE DELETE SYSTEM
    if AUTO_DELETE_TIME > 0:
        asyncio.create_task(delete_after_delay(message, AUTO_DELETE_TIME))


async def delete_after_delay(message: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


# --- 2. OWNER ONLY COMMANDS ---

# Setting 1: Check Total Groups Count (/stats)
@app.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return  # Non-owner ko response nahi milega

    groups = get_all_groups()
    await message.reply_text(f"📊 **Bot Status:**\n\nBot abhi **{len(groups)}** groups me added hai.")


# Setting 2: Broadcast Message/Link to All Groups (/broadcast)
@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    if not message.reply_to_message and len(message.command) < 2:
        await message.reply_text("❌ Usage:\n1. `/broadcast Hello`\n2. Kisi message/photo ko `/broadcast` se reply karein.")
        return

    groups = get_all_groups()
    success = 0
    failed = 0

    status_msg = await message.reply_text("🚀 Broadcast shuru ho raha hai...")

    for chat_id in groups:
        try:
            if message.reply_to_message:
                await message.reply_to_message.copy(chat_id)
            else:
                text = message.text.split(None, 1)[1]
                await client.send_message(chat_id, text)
            success += 1
            await asyncio.sleep(0.3)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            failed += 1
            remove_group(chat_id) # Bot jis group se nikal gaya ho use DB se hata dega

    await status_msg.edit_text(f"✅ **Broadcast Done!**\n\n• **Success:** {success} groups\n• **Failed:** {failed} groups")


# Main Event Loop Startup Function
async def main():
    await app.start()
    print("Bot successfully started!")
    await idle()
    await app.stop()

# Execution Entry Point
if __name__ == "__main__":
    loop.run_until_complete(main())
