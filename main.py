import os
import re
import random
import asyncio
import html
import time
from datetime import datetime
from aiohttp import web
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# ======================= CONFIGURATION =======================
BOT_TOKEN = "8822939259:AAGxqsUpMXIs1U01PAKkLJcCWqzHblf6Uog"
ADMIN_ID = 5834588787
CHANNEL_LINK = "https://t.me/Gmail_arena"
SUPPORT_USER = "@sxhivv"
RAW_DB_URL = os.environ.get("DATABASE_URL", "")
TASK_TIMEOUT_SECONDS = 1800  # 30 Minutes
# =============================================================

def get_clean_db_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    url = re.sub(r'([&?])channel_binding=[^&]*(&?)', r'\1', url)
    url = url.rstrip("&").rstrip("?")
    return url

DATABASE_URL = get_clean_db_url(RAW_DB_URL)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db_pool = None

UPI_REGEX = re.compile(r'^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$')
BEP20_REGEX = re.compile(r'^0x[a-fA-F0-9]{40}$')

# ======================= DATABASE SETUP =======================
async def init_db():
    global db_pool
    print("Connecting to Neon PostgreSQL...")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance NUMERIC(10, 2) DEFAULT 0.00,
                total_submitted INT DEFAULT 0,
                referred_by BIGINT DEFAULT NULL,
                is_banned BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS task_stock (
                id SERIAL PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                dob_month TEXT,
                dob_day TEXT,
                dob_year TEXT,
                email TEXT UNIQUE,
                password TEXT,
                status TEXT DEFAULT 'available',
                assigned_to BIGINT DEFAULT NULL,
                assigned_at BIGINT DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                acc_type TEXT,
                email TEXT,
                password TEXT,
                recovery TEXT,
                two_fa TEXT,
                is_old TEXT DEFAULT 'No',
                status TEXT DEFAULT 'pending',
                rejection_reason TEXT DEFAULT '',
                created_at TEXT,
                stock_ref_id INT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                order_id TEXT UNIQUE,
                user_id BIGINT,
                amount NUMERIC(10, 2),
                method TEXT DEFAULT 'UPI',
                payout_address TEXT,
                upi_id TEXT,
                utr TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

        # Auto-migration columns check
        await conn.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
            ALTER TABLE task_stock ADD COLUMN IF NOT EXISTS assigned_at BIGINT DEFAULT 0;
            ALTER TABLE submissions ADD COLUMN IF NOT EXISTS stock_ref_id INT DEFAULT NULL;
            ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS method TEXT DEFAULT 'UPI';
            ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS payout_address TEXT;
        """)

        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ('rate_readymade', '12.0') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('rate_botdata', '15.0') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('ref_bonus', '1.0') ON CONFLICT (key) DO NOTHING;
        """)
    print("Database connection ready!")

async def is_user_banned(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        val = await conn.fetchval("SELECT is_banned FROM users WHERE user_id=$1", user_id)
        return bool(val)

async def get_setting(key: str, default: float = 15.0):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return float(row['value']) if row else default

async def set_setting(key: str, value: float):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = $2
        """, key, str(value))

async def get_available_stock_count():
    async with db_pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM task_stock WHERE status='available'")
        return val or 0

async def ensure_user(user_id: int, username: str = "", referrer_id: int = None):
    async with db_pool.acquire() as conn:
        exists = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", user_id)
        if not exists:
            ref = referrer_id if (referrer_id and referrer_id != user_id) else None
            await conn.execute("""
                INSERT INTO users (user_id, username, balance, total_submitted, referred_by, is_banned)
                VALUES ($1, $2, 0.00, 0, $3, FALSE)
            """, user_id, username, ref)
        else:
            await conn.execute("UPDATE users SET username=$1 WHERE user_id=$2", username, user_id)

# ======================= BACKGROUND 30-MIN EXPIRY WORKER =======================
async def task_expiry_worker():
    while True:
        try:
            now_ts = int(time.time())
            async with db_pool.acquire() as conn:
                expired_tasks = await conn.fetch("""
                    SELECT id, assigned_to, email FROM task_stock 
                    WHERE status='assigned' AND ($1 - assigned_at) > $2
                """, now_ts, TASK_TIMEOUT_SECONDS)

                for task in expired_tasks:
                    task_id = task['id']
                    assigned_uid = task['assigned_to']
                    await conn.execute("""
                        UPDATE task_stock 
                        SET status='available', assigned_to=NULL, assigned_at=0 
                        WHERE id=$1
                    """, task_id)

                    if assigned_uid:
                        try:
                            await bot.send_message(
                                chat_id=assigned_uid,
                                text=(
                                    "⏰ <b>Task Time Expired! (30 Minutes Over)</b>\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"Your allocated task for <code>{task['email']}</code> was not submitted in time.\n"
                                    "The credentials have been returned to the public stock.\n\n"
                                    "Tap <b>⚡ Submit Gmail Account</b> whenever you are ready to claim a fresh task."
                                ),
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
        except Exception as e:
            print(f"Expiry worker error: {e}")
        await asyncio.sleep(30)

# ======================= BROADCAST SYSTEM =======================
async def broadcast_price_update(label: str, new_price: float):
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_banned=FALSE")

    broadcast_msg = (
        "🚀 <b>PRICE UPDATE ALERT!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"The reward rate for <b>{label}</b> has been updated to:\n\n"
        f"💰 <b>₹{new_price:.2f} per account!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap <b>⚡ Submit Gmail Account</b> below to start earning at the new rate!"
    )

    sent = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u['user_id'], text=broadcast_msg, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    return sent

# ======================= KEYBOARDS =======================
def kb_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡ Submit Gmail Account")],
            [KeyboardButton(text="📊 My Submissions"), KeyboardButton(text="💼 My Wallet")],
            [KeyboardButton(text="👥 Refer & Earn"), KeyboardButton(text="📢 Official Channel")],
            [KeyboardButton(text="💬 24/7 Support")]
        ],
        resize_keyboard=True
    )

def kb_sub_mode():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📁 Readymade Gmail"), KeyboardButton(text="⚡ Bot Task Account")],
            [KeyboardButton(text="❌ Cancel")]
        ],
        resize_keyboard=True
    )

def kb_bot_task_action():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Done / Created")],
            [KeyboardButton(text="❌ Cancel")]
        ],
        resize_keyboard=True
    )

def kb_cancel():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

def kb_recovery():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip Recovery Email")],
            [KeyboardButton(text="❌ Cancel")]
        ],
        resize_keyboard=True
    )

def kb_account_age():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📆 Older than 30 Days"), KeyboardButton(text="🆕 Fresh Account")],
            [KeyboardButton(text="❌ Cancel")]
        ],
        resize_keyboard=True
    )

def kb_2fa():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔐 Add 2FA Secret Key (Faster Payout)")],
            [KeyboardButton(text="⚡ Submit Without 2FA")],
            [KeyboardButton(text="❌ Cancel")]
        ],
        resize_keyboard=True
    )

def build_task_card_text(row: dict, r_bot: float, assigned_at: int):
    now_ts = int(time.time())
    elapsed = now_ts - assigned_at
    remaining = max(0, TASK_TIMEOUT_SECONDS - elapsed)
    mins, secs = divmod(remaining, 60)

    text = (
        f"⚡ <b>Target Registration Credentials (Reward: ₹{r_bot:.2f}):</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• First Name   : <code>{html.escape(row['first_name'])}</code>\n"
        f"• Last Name    : <code>{html.escape(row['last_name'])}</code>\n"
        f"• Date of Birth: <code>{html.escape(row['dob_month'])} {html.escape(str(row['dob_day']))}, {html.escape(str(row['dob_year']))}</code>\n"
        f"• Suggested Mail: <code>{html.escape(row['email'])}</code>\n"
        f"• Password     : <code>{html.escape(row['password'])}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>Time Remaining:</b> <b>{mins}m {secs:02d}s</b> (30 Min Window)\n\n"
        "⚠️ <b>STRICT WARNING:</b>\n"
        "1. Create the account using <b>EXACT credentials above</b>.\n"
        "2. Do NOT press 'Done' without creating the account. Submitting fake or unprocessed data will result in a <b>Permanent Account Ban</b>!\n\n"
        "➡️ Create this Gmail on Google, then tap <b>✅ Done / Created</b> below:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Refresh Timer", callback_data=f"reftimer_{row['id']}")
    ]])
    return text, kb

# ======================= FSM STATES =======================
class SubmitState(StatesGroup):
    choosing_mode = State()
    waiting_for_task_action = State()
    waiting_for_email = State()
    waiting_for_password = State()
    waiting_for_recovery = State()
    waiting_for_age = State()
    waiting_for_2fa_choice = State()
    waiting_for_2fa_key = State()

class WithdrawState(StatesGroup):
    choosing_method = State()
    waiting_for_upi = State()
    choosing_crypto_type = State()
    waiting_for_binance_uid = State()
    waiting_for_bep20_address = State()

class AdminState(StatesGroup):
    waiting_for_bulk_stock = State()
    waiting_for_rate_type = State()
    waiting_for_new_rate = State()
    waiting_for_addbal_id = State()
    waiting_for_addbal_amount = State()
    waiting_for_custom_reject = State()
    waiting_for_utr = State()
    waiting_for_ban_uid = State()

# ======================= BAN CHECK MIDDLEWARE =======================
@dp.message.outer_middleware()
async def ban_filter_middleware(handler, event: types.Message, data):
    if event.from_user and await is_user_banned(event.from_user.id):
        if event.from_user.id != ADMIN_ID:
            await event.answer("🚫 <b>Your account has been permanently suspended for policy violations.</b>", parse_mode="HTML")
            return
    return await handler(event, data)

# ======================= CANCEL ACTION =======================
@dp.message(F.text == "❌ Cancel")
async def cancel_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    assigned_stock_id = data.get("assigned_stock_id")
    
    if assigned_stock_id:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE task_stock SET status='available', assigned_to=NULL, assigned_at=0 WHERE id=$1", assigned_stock_id)

    await state.clear()
    await message.answer("🔄 Operation cancelled. Returning to main menu:", reply_markup=kb_main_menu())

# ======================= START & DASHBOARD =======================
@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    args = message.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    uid = message.from_user.id
    uname = message.from_user.username or message.from_user.first_name
    await ensure_user(uid, uname, ref_id)

    r_bot = await get_setting("rate_botdata", 15.0)
    r_ready = await get_setting("rate_readymade", 12.0)

    msg = (
        f"👋 <b>Welcome, {html.escape(message.from_user.first_name)}!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Earn instant money by providing verified Google accounts.\n\n"
        "💰 <b>Current Rates:</b>\n"
        f"• ⚡ <b>Bot Task Creation:</b> ₹{r_bot:.2f} per account\n"
        f"• 📁 <b>Readymade Gmail :</b> ₹{r_ready:.2f} per account\n\n"
        "⏱ <b>Audit Window:</b> 24 to 48 Hours\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select an option below to start:"
    )
    await message.answer(msg, parse_mode="HTML", reply_markup=kb_main_menu())

@dp.message(F.text == "💬 24/7 Support")
async def support_handler(message: types.Message):
    await message.answer(
        f"💬 <b>Direct Support:</b>\n"
        f"• Support Manager: {SUPPORT_USER}\n"
        f"• Community Channel: {CHANNEL_LINK}\n\n"
        "Reach out directly for any account or payout inquiries.",
        parse_mode="HTML"
    )

@dp.message(F.text == "📢 Official Channel")
async def channel_handler(message: types.Message):
    await message.answer(
        f"📢 <b>Official Telegram Channel:</b>\n{CHANNEL_LINK}\n\nFollow for real-time payment proofs and notices.",
        parse_mode="HTML"
    )

@dp.message(F.text == "👥 Refer & Earn")
async def refer_handler(message: types.Message):
    uid = message.from_user.id
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={uid}"
    bonus = await get_setting("ref_bonus", 1.0)

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referred_by=$1", uid)

    text = (
        "👥 <b>Affiliate Program</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Invite suppliers and friends to earn passive commission!\n\n"
        f"• Total Referrals: <b>{count or 0}</b> users\n"
        f"• Commission: <b>₹{bonus:.2f}</b> on every approved account\n\n"
        "🔗 <b>Your Referral Link:</b>\n"
        f"<code>{link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# ======================= WALLET & WITHDRAWALS =======================
@dp.message(F.text == "💼 My Wallet")
async def wallet_handler(message: types.Message):
    uid = message.from_user.id
    await ensure_user(uid, message.from_user.username or message.from_user.first_name)

    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)
        balance = float(bal) if bal is not None else 0.0

    r1 = await get_setting("rate_readymade", 12.0)
    r2 = await get_setting("rate_botdata", 15.0)
    min_p = min(r1, r2)

    text = (
        "💼 <b>Financial Wallet Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Available Balance:</b> <b>₹{balance:.2f}</b>\n"
        f"💳 <b>Minimum Withdrawal:</b> ₹{min_p:.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Direct UPI Bank Transfer or Crypto (USDT BEP-20 / Binance UID)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Request Withdrawal", callback_data="claim_funds")],
        [InlineKeyboardButton(text="📜 Payout History", callback_data="view_payout_history")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "view_payout_history")
async def payout_history_call(call: types.CallbackQuery):
    uid = call.from_user.id
    async with db_pool.acquire() as conn:
        payouts = await conn.fetch("""
            SELECT order_id, amount, method, payout_address, upi_id, utr, status, created_at 
            FROM withdrawals WHERE user_id=$1 ORDER BY id DESC LIMIT 8
        """, uid)

    text = "📜 <b>Withdrawal Transaction Invoices:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if not payouts:
        text += "<i>No withdrawal requests placed yet.</i>\n"
    else:
        for p in payouts:
            st = str(p['status']).lower()
            badge = "🟢 PAID" if st == "paid" else "⏳ PENDING"
            method_str = p['method'] or "UPI"
            address_str = p['payout_address'] or p['upi_id'] or "N/A"
            
            text += f"<b>Order ID:</b> <code>{p['order_id']}</code>\n"
            text += f"💵 Amount: <b>₹{float(p['amount']):.2f}</b> | Status: {badge}\n"
            text += f"🏷 Method: <b>{method_str}</b>\n"
            text += f"🎯 Target: <code>{html.escape(address_str)}</code>\n"
            text += f"📅 Date: {p['created_at'] or 'Recent'}\n"
            if p['utr']:
                text += f"🧾 Ref / TxID: <code>{html.escape(p['utr'])}</code>\n"
            text += "────────────────────────\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Back to Wallet", callback_data="back_to_wallet")
    ]])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "back_to_wallet")
async def back_to_wallet_call(call: types.CallbackQuery):
    uid = call.from_user.id
    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)
        balance = float(bal) if bal is not None else 0.0

    r1 = await get_setting("rate_readymade", 12.0)
    r2 = await get_setting("rate_botdata", 15.0)
    min_p = min(r1, r2)

    text = (
        "💼 <b>Financial Wallet Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Available Balance:</b> <b>₹{balance:.2f}</b>\n"
        f"💳 <b>Minimum Withdrawal:</b> ₹{min_p:.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Direct UPI Bank Transfer or Crypto (USDT BEP-20 / Binance UID)."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Request Withdrawal", callback_data="claim_funds")],
        [InlineKeyboardButton(text="📜 Payout History", callback_data="view_payout_history")]
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

# --- WITHDRAWAL GATEWAY SELECTION ---
@dp.callback_query(F.data == "claim_funds")
async def cashout_initiate(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)
        balance = float(bal) if bal is not None else 0.0

    r1 = await get_setting("rate_readymade", 12.0)
    r2 = await get_setting("rate_botdata", 15.0)
    min_p = min(r1, r2)

    if balance < min_p:
        await call.answer(f"Minimum threshold is ₹{min_p:.2f}. Your balance is ₹{balance:.2f}.", show_alert=True)
        return

    method_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇮🇳 UPI Transfer", callback_data="wm_upi")],
        [InlineKeyboardButton(text="⚡ Crypto (USDT / Binance)", callback_data="wm_crypto")]
    ])
    await call.message.answer(
        "💳 <b>Select Withdrawal Gateway:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>UPI Transfer:</b> Fast domestic bank transfer.\n"
        "2️⃣ <b>Crypto Payout:</b> Binance Pay UID or USDT (BEP-20).\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below:",
        parse_mode="HTML",
        reply_markup=method_kb
    )
    await state.set_state(WithdrawState.choosing_method)
    await call.answer()

@dp.callback_query(F.data == "wm_upi", WithdrawState.choosing_method)
async def cashout_choose_upi(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "📱 <b>Please enter your UPI ID for settlement:</b>\n"
        "<i>Valid Handles: @okaxis, @paytm, @ybl, @oksbi, @okhdfcbank, @fam, etc.</i>\n\n"
        "Example: <code>9876543210@paytm</code> or <code>username@okaxis</code>",
        parse_mode="HTML",
        reply_markup=kb_cancel()
    )
    await state.set_state(WithdrawState.waiting_for_upi)
    await call.answer()

@dp.callback_query(F.data == "wm_crypto", WithdrawState.choosing_method)
async def cashout_choose_crypto(call: types.CallbackQuery, state: FSMContext):
    crypto_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟡 Binance UID (Pay ID)", callback_data="c_binance")],
        [InlineKeyboardButton(text="🟢 USDT (BEP-20 Network)", callback_data="c_bep20")]
    ])
    await call.message.answer(
        "⚡ <b>Select Crypto Payout Option:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>Binance UID:</b> Instant transfer with 0 network fees.\n"
        "2️⃣ <b>USDT (BEP-20):</b> Direct wallet transfer on Binance Smart Chain.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select your network:",
        parse_mode="HTML",
        reply_markup=crypto_kb
    )
    await state.set_state(WithdrawState.choosing_crypto_type)
    await call.answer()

@dp.callback_query(F.data == "c_binance", WithdrawState.choosing_crypto_type)
async def cashout_choose_binance(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "🟡 <b>Enter your 8–10 digit Binance User ID (UID):</b>\n"
        "<i>(Found on your Binance app profile header)</i>\n\n"
        "Example: <code>183948291</code>",
        parse_mode="HTML",
        reply_markup=kb_cancel()
    )
    await state.set_state(WithdrawState.waiting_for_binance_uid)
    await call.answer()

@dp.callback_query(F.data == "c_bep20", WithdrawState.choosing_crypto_type)
async def cashout_choose_bep20(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "🟢 <b>Enter your USDT BEP-20 (BSC) Wallet Address:</b>\n"
        "<i>(Starts with <code>0x</code>)</i>\n\n"
        "⚠️ <b>Note:</b> Send only BEP-20 (Binance Smart Chain) address.",
        parse_mode="HTML",
        reply_markup=kb_cancel()
    )
    await state.set_state(WithdrawState.waiting_for_bep20_address)
    await call.answer()

@dp.message(WithdrawState.waiting_for_upi)
async def cashout_process_upi(message: types.Message, state: FSMContext):
    upi = message.text.strip().lower()

    if not UPI_REGEX.match(upi) or " " in upi:
        await message.answer(
            "⚠️ <b>Invalid UPI Address!</b>\n"
            "Please provide a valid address with handles like <code>@okaxis</code>, <code>@paytm</code>, <code>@ybl</code>, <code>@oksbi</code>.\n\n"
            "Try again or press <b>❌ Cancel</b>:",
            parse_mode="HTML"
        )
        return
    await finalize_cashout_order(message, state, "UPI", upi)

@dp.message(WithdrawState.waiting_for_binance_uid)
async def cashout_process_binance_uid(message: types.Message, state: FSMContext):
    uid_str = message.text.strip()
    if not uid_str.isdigit() or len(uid_str) < 6 or len(uid_str) > 12:
        await message.answer(
            "⚠️ <b>Invalid Binance UID!</b>\nMust be a valid 6-12 digit numeric user ID.\n\nTry again or press <b>❌ Cancel</b>:",
            parse_mode="HTML"
        )
        return
    await finalize_cashout_order(message, state, "Binance UID", uid_str)

@dp.message(WithdrawState.waiting_for_bep20_address)
async def cashout_process_bep20(message: types.Message, state: FSMContext):
    addr = message.text.strip()
    if not BEP20_REGEX.match(addr):
        await message.answer(
            "⚠️ <b>Invalid BEP-20 Address!</b>\nMust be a 42-character address starting with <code>0x</code>.\n\nTry again or press <b>❌ Cancel</b>:",
            parse_mode="HTML"
        )
        return
    await finalize_cashout_order(message, state, "USDT (BEP-20)", addr)

async def finalize_cashout_order(message: types.Message, state: FSMContext, method: str, payout_target: str):
    uid = message.from_user.id
    order_id = f"GMA-W-{random.randint(10000, 99999)}"
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)
        balance = float(bal) if bal is not None else 0.0

        if balance <= 0:
            await message.answer("⚠️ Insufficient balance for cashout.", reply_markup=kb_main_menu())
            await state.clear()
            return

        await conn.execute("UPDATE users SET balance=0.00 WHERE user_id=$1", uid)
        w_id = await conn.fetchval("""
            INSERT INTO withdrawals (order_id, user_id, amount, method, payout_address, upi_id, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $5, 'pending', $6) RETURNING id
        """, order_id, uid, balance, method, payout_target, now_str)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 Mark Paid & Assign TxID / Ref", callback_data=f"startpay_{w_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 <b>New Withdrawal Request: {order_id}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User: @{message.from_user.username} (ID: <code>{uid}</code>)\n"
            f"💵 Amount: <b>₹{balance:.2f}</b>\n"
            f"🏷 Method: <b>{method}</b>\n"
            f"🎯 Target Address: <code>{html.escape(payout_target)}</code>\n"
            f"📅 Placed: {now_str}"
        ),
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    await message.answer(
        f"✅ <b>Withdrawal Order #{order_id} Registered!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 Order ID     : <code>{order_id}</code>\n"
        f"💵 Payout Amount : <b>₹{balance:.2f}</b>\n"
        f"🏷 Method        : <b>{method}</b>\n"
        f"🎯 Destination   : <code>{html.escape(payout_target)}</code>\n"
        "⏳ Status        : <b>Processing Settlement</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "You can track this transaction in <b>💼 My Wallet ➔ Payout History</b>.",
        parse_mode="HTML",
        reply_markup=kb_main_menu()
    )
    await state.clear()

# ======================= ADMIN PAYOUT WITH UTR / TXID =======================
@dp.callback_query(F.data.startswith("startpay_"))
async def admin_pay_request_utr(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    w_id = int(call.data.split("_")[1])

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT order_id, amount, method, payout_address, upi_id, status FROM withdrawals WHERE id=$1", w_id)
        if not row or row['status'] != 'pending':
            await call.answer("This withdrawal is already processed!", show_alert=True)
            return

    target_addr = row['payout_address'] or row['upi_id']
    await state.update_data(target_wid=w_id)
    await call.message.reply(
        f"🧾 <b>Enter TxID / UTR / Reference for Order #{row['order_id']}:</b>\n"
        f"Amount: ₹{float(row['amount']):.2f} | Method: <b>{row['method']}</b>\n"
        f"Target: <code>{target_addr}</code>\n\n"
        "Type the reference number below:",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.waiting_for_utr)
    await call.answer()

@dp.message(AdminState.waiting_for_utr)
async def admin_save_utr(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    utr_code = message.text.strip()
    data = await state.get_data()
    w_id = data.get("target_wid")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT order_id, user_id, amount, method, payout_address, upi_id FROM withdrawals WHERE id=$1", w_id)
        if row:
            order_id = row['order_id']
            uid = row['user_id']
            amount = float(row['amount'])
            method = row['method']
            target_addr = row['payout_address'] or row['upi_id']

            await conn.execute("UPDATE withdrawals SET status='paid', utr=$1 WHERE id=$2", utr_code, w_id)
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"🎉 <b>Withdrawal Completed & Dispatched!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 Order ID     : <b>{order_id}</b>\n"
                        f"💵 Amount       : <b>₹{amount:.2f}</b>\n"
                        f"🏷 Method       : <b>{method}</b>\n"
                        f"🎯 Destination  : <code>{html.escape(target_addr)}</code>\n"
                        f"🔗 TxID / Ref   : <code>{html.escape(utr_code)}</code>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "Funds have been successfully transferred to your destination."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Error notifying: {e}")

    await message.answer(f"✅ Order <b>{order_id}</b> settled with Ref: <code>{utr_code}</code>", parse_mode="HTML")
    await state.clear()

# ======================= MY SUBMISSIONS DASHBOARD =======================
async def get_submissions_card(uid: int):
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1", uid)
        pending = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='pending'", uid)
        approved = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='approved'", uid)
        rejected = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='rejected'", uid)

        subs = await conn.fetch("""
            SELECT id, email, password, recovery, two_fa, is_old, status, rejection_reason, acc_type, created_at
            FROM submissions WHERE user_id=$1 ORDER BY id DESC LIMIT 10
        """, uid)

    card = (
        "📊 <b>Your Account Submissions</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total Submitted : <b>{total or 0}</b>\n"
        f"⏳ Under Review    : <b>{pending or 0}</b>\n"
        f"🟢 Approved        : <b>{approved or 0}</b>\n"
        f"🔴 Rejected        : <b>{rejected or 0}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Recent Submissions (Last 10):</b>\n\n"
    )

    if not subs:
        card += "<i>No accounts submitted yet.</i>\n"
    else:
        for row in subs:
            st = str(row['status']).lower()
            acc_type = "Task" if "Bot" in str(row['acc_type']) else "Ready"
            time_str = row['created_at'] or "Recent"

            card += f"<b>SUB #{row['id']} • {html.escape(row['email'])}</b> [{acc_type}]\n"
            card += f"📅 Submitted: <code>{time_str}</code>\n"

            if st == "approved":
                card += "🟢 Status: <b>✅ Verified & Credited</b>\n"
            elif st == "rejected":
                card += "🔴 Status: <b>Rejected</b>\n"
                card += f"⚠️ Reason: <i>{html.escape(row['rejection_reason'] or 'Credentials Failed')}</i>\n"
                card += f"🔑 Pass: <code>{html.escape(row['password'])}</code>"
                if row['recovery'] and row['recovery'] != 'None':
                    card += f" | Rec: <code>{html.escape(row['recovery'])}</code>"
                if row['two_fa'] and row['two_fa'] != 'None':
                    card += f"\n🔐 2FA: <code>{html.escape(row['two_fa'])}</code>"
                card += "\n"
            else:
                card += "⏳ Status: <b>In Review Queue</b>\n"
                card += f"🔑 Pass: <code>{html.escape(row['password'])}</code>"
                if row['recovery'] and row['recovery'] != 'None':
                    card += f" | Rec: <code>{html.escape(row['recovery'])}</code>"
                if row['two_fa'] and row['two_fa'] != 'None':
                    card += f"\n🔐 2FA: <code>{html.escape(row['two_fa'])}</code>"
                card += "\n"

            card += "────────────────────────\n"

    refresh_btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Refresh Status", callback_data="reload_history")
    ]])
    return card, refresh_btn

@dp.message(F.text == "📊 My Submissions")
async def submissions_view(message: types.Message):
    card, kb = await get_submissions_card(message.from_user.id)
    await message.answer(card, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "reload_history")
async def submissions_reload(call: types.CallbackQuery):
    card, kb = await get_submissions_card(call.from_user.id)
    try:
        await call.message.edit_text(card, parse_mode="HTML", reply_markup=kb)
        await call.answer("Status refreshed!")
    except Exception:
        await call.answer("Already up to date.")

# ======================= ACCOUNT SUBMISSION WORKFLOW =======================
@dp.message(F.text == "⚡ Submit Gmail Account")
async def submit_start_mode(message: types.Message, state: FSMContext):
    r_ready = await get_setting("rate_readymade", 12.0)
    r_bot = await get_setting("rate_botdata", 15.0)

    text = (
        "⚡ <b>Select Account Submission Mode:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>📁 Readymade Gmail:</b> <b>₹{r_ready:.2f}</b> per account\n"
        "• Submit pre-created active Gmail accounts.\n"
        "• Accounts must be clean, active, and accessible.\n\n"
        f"2️⃣ <b>⚡ Bot Task Account:</b> <b>₹{r_bot:.2f}</b> per account\n"
        "• We provide specific Name, DOB, and Password.\n"
        "• <b>Time Window:</b> 30 Minutes to create and submit.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb_sub_mode())
    await state.set_state(SubmitState.choosing_mode)

# ----------------- FLOW 1: BOT TASK ACCOUNT (WITH 30 MIN TIMER) -----------------
@dp.message(SubmitState.choosing_mode, F.text == "⚡ Bot Task Account")
async def submit_task_mode(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    r_bot = await get_setting("rate_botdata", 15.0)
    now_ts = int(time.time())

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, first_name, last_name, dob_month, dob_day, dob_year, email, password 
            FROM task_stock WHERE status='available' LIMIT 1
        """)
        if not row:
            await message.answer(
                "⚠️ <b>Task Stock Empty!</b>\nAll bot-data tasks are currently claimed. Please use 'Readymade Gmail' or wait for restock.",
                reply_markup=kb_main_menu()
            )
            await state.clear()
            return

        stock_id = row['id']
        await conn.execute("""
            UPDATE task_stock 
            SET status='assigned', assigned_to=$1, assigned_at=$2 
            WHERE id=$3
        """, uid, now_ts, stock_id)

    await state.update_data(
        acc_type="Bot-Data Task",
        assigned_stock_id=stock_id,
        email=row['email'],
        password=row['password'],
        assigned_at=now_ts
    )

    card_text, timer_kb = build_task_card_text(dict(row), r_bot, now_ts)
    await message.answer(card_text, parse_mode="HTML", reply_markup=timer_kb)
    await message.answer("Tap <b>✅ Done / Created</b> below once you create it:", parse_mode="HTML", reply_markup=kb_bot_task_action())
    await state.set_state(SubmitState.waiting_for_task_action)

@dp.callback_query(F.data.startswith("reftimer_"))
async def refresh_task_timer(call: types.CallbackQuery, state: FSMContext):
    task_id = int(call.data.split("_")[1])
    r_bot = await get_setting("rate_botdata", 15.0)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM task_stock WHERE id=$1", task_id)
        if not row or row['status'] != 'assigned' or row['assigned_to'] != call.from_user.id:
            await call.answer("This task is no longer active or has expired.", show_alert=True)
            return

    new_text, timer_kb = build_task_card_text(dict(row), r_bot, row['assigned_at'])
    try:
        await call.message.edit_text(new_text, parse_mode="HTML", reply_markup=timer_kb)
        await call.answer("Timer updated!")
    except Exception:
        await call.answer("Time refreshed!")

@dp.message(SubmitState.waiting_for_task_action, F.text == "✅ Done / Created")
async def bot_task_done_clicked(message: types.Message, state: FSMContext):
    data = await state.get_data()
    email = data.get("email")
    pwd = data.get("password")
    acc_type = data.get("acc_type")
    stock_id = data.get("assigned_stock_id")
    assigned_at = data.get("assigned_at", 0)
    now_ts = int(time.time())

    # Check 30-min expiration
    if (now_ts - assigned_at) > TASK_TIMEOUT_SECONDS:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE task_stock SET status='available', assigned_to=NULL, assigned_at=0 WHERE id=$1", stock_id)
        await message.answer("⏰ <b>Your 30-minute window expired!</b>\nThe task has been reclaimed. Please request a new task.", reply_markup=kb_main_menu())
        await state.clear()
        return

    user = message.from_user
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    await ensure_user(user.id, user.username or user.first_name)

    async with db_pool.acquire() as conn:
        sub_id = await conn.fetchval("""
            INSERT INTO submissions (user_id, acc_type, email, password, recovery, two_fa, is_old, status, created_at, stock_ref_id)
            VALUES ($1, $2, $3, $4, 'None', 'None', 'Fresh (Task)', 'pending', $5, $6) RETURNING id
        """, user.id, acc_type, email, pwd, now_str, stock_id)
        await conn.execute("UPDATE users SET total_submitted = total_submitted + 1 WHERE user_id=$1", user.id)
        # Mark task permanently submitted
        await conn.execute("UPDATE task_stock SET status='submitted' WHERE id=$1", stock_id)

    r_est = await get_setting("rate_botdata", 15.0)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Approve (+₹{r_est:.2f})", callback_data=f"adm_app_{sub_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rejmenu_{sub_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📥 <b>New Submission Alert [SUB #{sub_id}]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Submission ID: <b>SUB #{sub_id}</b>\n"
            f"👤 User: @{user.username} (ID: <code>{user.id}</code>)\n"
            f"🏷 Type: <b>{acc_type}</b> (Reward: ₹{r_est:.2f})\n\n"
            f"📧 Email    : <code>{html.escape(email)}</code>\n"
            f"🔑 Password : <code>{html.escape(pwd)}</code>\n"
            f"📅 Submitted: {now_str}"
        ),
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    confirm_card = (
        "✅ <b>Task Submitted Successfully!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Submission ID : SUB #{sub_id}</b>\n"
        f"📧 Email         : <code>{html.escape(email)}</code>\n"
        f"💵 Payout        : <b>₹{r_est:.2f}</b> (Upon verification)\n"
        "⏳ Status        : <b>Under Review Queue</b>\n\n"
        "Track live progress inside <b>📊 My Submissions</b>."
    )
    await message.answer(confirm_card, parse_mode="HTML", reply_markup=kb_main_menu())
    await state.clear()

# ----------------- FLOW 2: READYMADE GMAIL -----------------
@dp.message(SubmitState.choosing_mode, F.text == "📁 Readymade Gmail")
async def submit_premade_mode(message: types.Message, state: FSMContext):
    r_ready = await get_setting("rate_readymade", 12.0)
    await state.update_data(acc_type="Readymade")
    await message.answer(
        f"📁 <b>Readymade Account Submission (Rate: ₹{r_ready:.2f})</b>\n\n"
        "📧 <b>Please enter your Gmail address:</b>\n"
        "<i>(e.g. <code>username123@gmail.com</code>)</i>",
        parse_mode="HTML",
        reply_markup=kb_cancel()
    )
    await state.set_state(SubmitState.waiting_for_email)

@dp.message(SubmitState.waiting_for_email)
async def submit_get_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if "@gmail.com" not in email.lower():
        await message.answer("⚠️ <b>Invalid Email:</b> Must end with <code>@gmail.com</code>. Try again:", parse_mode="HTML")
        return
    await state.update_data(email=email)
    await message.answer("🔑 <b>Please enter the Password for this account:</b>", parse_mode="HTML", reply_markup=kb_cancel())
    await state.set_state(SubmitState.waiting_for_password)

@dp.message(SubmitState.waiting_for_password)
async def submit_get_password(message: types.Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await message.answer(
        "🛡 <b>Recovery Email Check:</b>\nIf linked, send the recovery address below or tap <b>Skip</b>.",
        parse_mode="HTML",
        reply_markup=kb_recovery()
    )
    await state.set_state(SubmitState.waiting_for_recovery)

@dp.message(SubmitState.waiting_for_recovery, F.text == "⏭ Skip Recovery Email")
async def submit_skip_recovery(message: types.Message, state: FSMContext):
    await state.update_data(recovery="None")
    await ask_account_age(message, state)

@dp.message(SubmitState.waiting_for_recovery)
async def submit_input_recovery(message: types.Message, state: FSMContext):
    await state.update_data(recovery=message.text.strip())
    await ask_account_age(message, state)

async def ask_account_age(message: types.Message, state: FSMContext):
    await message.answer(
        "📆 <b>Is this account older than 30 days?</b>",
        parse_mode="HTML",
        reply_markup=kb_account_age()
    )
    await state.set_state(SubmitState.waiting_for_age)

@dp.message(SubmitState.waiting_for_age, F.text.in_({"📆 Older than 30 Days", "🆕 Fresh Account"}))
async def submit_get_age(message: types.Message, state: FSMContext):
    is_old = "Yes" if "Older" in message.text else "No"
    await state.update_data(is_old=is_old)

    await message.answer(
        "🔐 <b>Two-Factor Authentication (2FA):</b>\n"
        "Setting up 2FA secret keys speeds up verification queue significantly.\n\n"
        "You can submit with or without 2FA key:",
        parse_mode="HTML",
        reply_markup=kb_2fa()
    )
    await state.set_state(SubmitState.waiting_for_2fa_choice)

@dp.message(SubmitState.waiting_for_2fa_choice, F.text == "⚡ Submit Without 2FA")
async def submit_finish_no_2fa(message: types.Message, state: FSMContext):
    await state.update_data(two_fa="None")
    await finalize_readymade_submission(message, state)

@dp.message(SubmitState.waiting_for_2fa_choice, F.text == "🔐 Add 2FA Secret Key (Faster Payout)")
async def submit_req_2fa(message: types.Message, state: FSMContext):
    await message.answer("🔑 <b>Paste your 2FA Secret Key / Backup Code below:</b>", parse_mode="HTML", reply_markup=kb_cancel())
    await state.set_state(SubmitState.waiting_for_2fa_key)

@dp.message(SubmitState.waiting_for_2fa_key)
async def submit_finish_with_2fa(message: types.Message, state: FSMContext):
    await state.update_data(two_fa=message.text.strip())
    await finalize_readymade_submission(message, state)

async def finalize_readymade_submission(message: types.Message, state: FSMContext):
    data = await state.get_data()
    acc_type = data["acc_type"]
    email = data["email"]
    pwd = data["password"]
    rec = data["recovery"]
    is_old = data.get("is_old", "No")
    two_fa = data["two_fa"]
    user = message.from_user
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    await ensure_user(user.id, user.username or user.first_name)

    async with db_pool.acquire() as conn:
        sub_id = await conn.fetchval("""
            INSERT INTO submissions (user_id, acc_type, email, password, recovery, two_fa, is_old, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8) RETURNING id
        """, user.id, acc_type, email, pwd, rec, two_fa, is_old, now_str)
        await conn.execute("UPDATE users SET total_submitted = total_submitted + 1 WHERE user_id=$1", user.id)

    r_est = await get_setting("rate_readymade", 12.0)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Approve (+₹{r_est:.2f})", callback_data=f"adm_app_{sub_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rejmenu_{sub_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📥 <b>New Submission Alert [SUB #{sub_id}]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Submission ID: <b>SUB #{sub_id}</b>\n"
            f"👤 User: @{user.username} (ID: <code>{user.id}</code>)\n"
            f"🏷 Type: <b>{acc_type}</b> (Reward: ₹{r_est:.2f})\n"
            f"📅 Vintage (>30 Days): <b>{is_old}</b>\n\n"
            f"📧 Email    : <code>{html.escape(email)}</code>\n"
            f"🔑 Password : <code>{html.escape(pwd)}</code>\n"
            f"🛡 Recovery : <code>{html.escape(rec)}</code>\n"
            f"🔐 2FA Key  : <code>{html.escape(two_fa)}</code>\n"
            f"📅 Submitted: {now_str}"
        ),
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    confirm_card = (
        "✅ <b>Account Submitted Successfully!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Submission ID : SUB #{sub_id}</b>\n"
        f"📧 Email         : <code>{html.escape(email)}</code>\n"
        f"💵 Payout        : <b>₹{r_est:.2f}</b> (Upon verification)\n"
        "⏳ Status        : <b>Under Review Queue</b>\n\n"
        "Track live progress inside <b>📊 My Submissions</b>."
    )
    await message.answer(confirm_card, parse_mode="HTML", reply_markup=kb_main_menu())
    await state.clear()

# ======================= ADMIN ACTIONS (WITH AUTO-RESTOCK ON REJECT) =======================
@dp.callback_query(F.data.startswith("adm_app_"))
async def admin_accept_sub(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[2])

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, email, status, acc_type FROM submissions WHERE id=$1", sub_id)
        if not row or str(row['status']).lower() != "pending":
            await call.answer("This account has already been processed!", show_alert=True)
            return

        uid = int(row['user_id'])
        mail = row['email']
        acc_type = row['acc_type']
        reward = await (get_setting("rate_botdata", 15.0) if "Bot" in str(acc_type) else get_setting("rate_readymade", 12.0))

        await conn.execute("UPDATE submissions SET status='approved' WHERE id=$1", sub_id)
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", reward, uid)
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)

        referrer = await conn.fetchval("SELECT referred_by FROM users WHERE user_id=$1", uid)
        if referrer:
            ref_bonus = await get_setting("ref_bonus", 1.0)
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", ref_bonus, referrer)
            try:
                await bot.send_message(
                    chat_id=referrer,
                    text=f"💎 <b>Referral Bonus!</b> Earned <b>₹{ref_bonus:.2f}</b> from referral SUB #{sub_id}."
                )
            except Exception:
                pass

    try:
        await bot.send_message(
            chat_id=uid,
            text=(
                f"🎉 <b>Account Verified & Approved!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 Submission: <b>SUB #{sub_id}</b>\n"
                f"📧 Account: <code>{html.escape(mail)}</code>\n"
                f"💵 Reward Credited: <b>+₹{reward:.2f}</b>\n"
                f"💼 Updated Balance: <b>₹{float(new_bal):.2f}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Funds are ready to withdraw in <b>💼 My Wallet</b>!"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Error notifying: {e}")

    await call.message.edit_text(f"{call.message.text}\n\n🟢 <b>STATUS: APPROVED (+₹{reward:.2f})</b>", parse_mode="HTML")
    await call.answer(f"Approved! +₹{reward:.2f} credited.")

@dp.callback_query(F.data.startswith("adm_rejmenu_"))
async def admin_reject_menu_open(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[2])
    async with db_pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM submissions WHERE id=$1", sub_id)
        if not st or str(st).lower() != "pending":
            await call.answer("Already processed!", show_alert=True)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Wrong Password", callback_data=f"rjact_{sub_id}_Wrong Password")],
        [InlineKeyboardButton(text="🔒 2FA / OTP Verification Challenge", callback_data=f"rjact_{sub_id}_2FA / OTP Locked")],
        [InlineKeyboardButton(text="⚠️ Account Disabled / Banned", callback_data=f"rjact_{sub_id}_Account Disabled")],
        [InlineKeyboardButton(text="✏️ Type Custom Reason", callback_data=f"rjcustom_{sub_id}")],
        [InlineKeyboardButton(text="🔙 Cancel Action", callback_data=f"rjcancel_{sub_id}")]
    ])
    await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("rjcancel_"))
async def admin_reject_undo(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    r_est = await get_setting("rate_readymade", 12.0)

    restore_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Approve (+₹{r_est:.2f})", callback_data=f"adm_app_{sub_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rejmenu_{sub_id}")
    ]])
    await call.message.edit_reply_markup(reply_markup=restore_kb)
    await call.answer()

@dp.callback_query(F.data.startswith("rjact_"))
async def admin_reject_quick(call: types.CallbackQuery):
    parts = call.data.split("_", 2)
    sub_id = int(parts[1])
    reason = parts[2]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, email, status, stock_ref_id FROM submissions WHERE id=$1", sub_id)
        if not row or str(row['status']).lower() != "pending":
            await call.answer("Task already processed!", show_alert=True)
            return

        uid = int(row['user_id'])
        mail = row['email']
        stock_ref = row['stock_ref_id']

        await conn.execute("UPDATE submissions SET status='rejected', rejection_reason=$1 WHERE id=$2", reason, sub_id)

        # Auto-return bot data to available stock pool if rejected!
        if stock_ref:
            await conn.execute("UPDATE task_stock SET status='available', assigned_to=NULL, assigned_at=0 WHERE id=$1", stock_ref)

    try:
        await bot.send_message(
            chat_id=uid,
            text=(
                f"🔴 <b>Submission Disqualified</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 Submission: <b>SUB #{sub_id}</b>\n"
                f"📧 Account: <code>{html.escape(mail)}</code>\n"
                f"⚠️ Reason: <b>{html.escape(reason)}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Please check credentials and submit fresh tasks."
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Error notifying: {e}")

    await call.message.edit_text(f"{call.message.text}\n\n🔴 <b>STATUS: REJECTED ({html.escape(reason)}) [Data Restocked]</b>", parse_mode="HTML")
    await call.answer("Rejected and restocked.")

@dp.callback_query(F.data.startswith("rjcustom_"))
async def admin_reject_custom_start(call: types.CallbackQuery, state: FSMContext):
    sub_id = int(call.data.split("_")[1])
    await state.update_data(target_sub_id=sub_id)
    await call.message.reply(f"✏️ <b>Enter custom rejection reason for SUB #{sub_id}:</b>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_custom_reject)
    await call.answer()

@dp.message(AdminState.waiting_for_custom_reject)
async def admin_reject_custom_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    sub_id = data.get("target_sub_id")
    reason = message.text.strip()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, email, stock_ref_id FROM submissions WHERE id=$1", sub_id)
        if row:
            uid = int(row['user_id'])
            mail = row['email']
            stock_ref = row['stock_ref_id']

            await conn.execute("UPDATE submissions SET status='rejected', rejection_reason=$1 WHERE id=$2", reason, sub_id)

            if stock_ref:
                await conn.execute("UPDATE task_stock SET status='available', assigned_to=NULL, assigned_at=0 WHERE id=$1", stock_ref)

            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"🔴 <b>Submission Disqualified</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🆔 Submission: <b>SUB #{sub_id}</b>\n"
                        f"📧 Account: <code>{html.escape(mail)}</code>\n"
                        f"⚠️ Reason: <b>{html.escape(reason)}</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "Details recorded in <b>📊 My Submissions</b>."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await message.answer(f"✅ SUB #{sub_id} rejected with reason: <b>{html.escape(reason)}</b> (Stock Returned)", parse_mode="HTML")
    await state.clear()

# ======================= ADMIN DASHBOARD (BAN / UNBAN SYSTEM) =======================
@dp.message(Command("admin"))
async def admin_terminal(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        pending_subs = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE LOWER(status)='pending'")
        pending_payouts = await conn.fetchval("SELECT COUNT(*) FROM withdrawals WHERE LOWER(status)='pending'")

    stock_count = await get_available_stock_count()
    r_ready = await get_setting("rate_readymade", 12.0)
    r_bot = await get_setting("rate_botdata", 15.0)
    r_ref = await get_setting("ref_bonus", 1.0)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Upload Task Stock", callback_data="adm_upload_stock")],
        [
            InlineKeyboardButton(text=f"⚙️ Readymade Rate (₹{r_ready:.2f})", callback_data="rate_change_readymade"),
            InlineKeyboardButton(text=f"⚙️ Bot Task Rate (₹{r_bot:.2f})", callback_data="rate_change_botdata")
        ],
        [
            InlineKeyboardButton(text=f"🎁 Referral Bonus (₹{r_ref:.2f})", callback_data="rate_change_ref"),
            InlineKeyboardButton(text="💳 Adjust Balance", callback_data="adm_add_bal")
        ],
        [InlineKeyboardButton(text="🚫 Ban / Unban User", callback_data="adm_toggle_ban")]
    ])

    card = (
        "👑 <b>Executive Admin Terminal</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users      : <b>{total_users or 0}</b>\n"
        f"📦 Available Stock  : <b>{stock_count}</b> profiles\n"
        f"⏳ Pending Audits   : <b>{pending_subs or 0}</b>\n"
        f"💸 Pending Payouts  : <b>{pending_payouts or 0}</b>\n\n"
        "💰 <b>Current Rates:</b>\n"
        f"• Readymade Account Rate : ₹{r_ready:.2f}\n"
        f"• Bot Task Account Rate  : ₹{r_bot:.2f}\n"
        f"• Referral Commission    : ₹{r_ref:.2f}"
    )
    await message.answer(card, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "adm_toggle_ban")
async def adm_toggle_ban_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await call.message.answer("Enter the Telegram User ID to Ban or Unban:")
    await state.set_state(AdminState.waiting_for_ban_uid)
    await call.answer()

@dp.message(AdminState.waiting_for_ban_uid)
async def adm_toggle_ban_process(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    raw_uid = message.text.strip()
    if not raw_uid.isdigit():
        await message.answer("⚠️ Please send a valid numeric Telegram ID.")
        return

    uid = int(raw_uid)
    await ensure_user(uid)

    async with db_pool.acquire() as conn:
        curr_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id=$1", uid)
        new_status = not curr_banned
        await conn.execute("UPDATE users SET is_banned=$1 WHERE user_id=$2", new_status, uid)

    status_str = "🚫 <b>PERMANENTLY BANNED</b>" if new_status else "🟢 <b>UNBANNED / ACTIVE</b>"
    await message.answer(f"User <code>{uid}</code> status is now: {status_str}", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "adm_upload_stock")
async def adm_stock_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    msg = (
        "📥 <b>Upload Task Stock (WhatsApp / Plain Format):</b>\n\n"
        "<b>Accepted Format:</b>\n"
        "<code>First name: John\n"
        "Last name: Krum\n"
        "---------\n"
        "Date of birth\n"
        "Month: July | Day: 12 | Year: 1986\n"
        "---------\n"
        "Email: johnkrumb623@gmail.com\n"
        "---------\n"
        "Password: 9VQZqgHRv6WU</code>\n\n"
        "Paste your batch below:"
    )
    await call.message.answer(msg, parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_bulk_stock)
    await call.answer()

@dp.message(AdminState.waiting_for_bulk_stock)
async def adm_stock_process(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.strip()
    added = 0

    async with db_pool.acquire() as conn:
        if "first name:" in text.lower() and "email:" in text.lower():
            blocks = re.split(r'(?i)(?=First\s*name\s*:)', text)
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                fn_m = re.search(r'(?i)First\s*name\s*:\s*([^\n\r]+)', block)
                ln_m = re.search(r'(?i)Last\s*name\s*:\s*([^\n\r]+)', block)
                m_m = re.search(r'(?i)Month\s*:\s*([^|\n\r]+)', block)
                d_m = re.search(r'(?i)Day\s*:\s*([^|\n\r]+)', block)
                y_m = re.search(r'(?i)Year\s*:\s*([^\n\r]+)', block)
                em_m = re.search(r'(?i)Email\s*:\s*([a-zA-Z0-9._%+-]+@gmail\.com)', block)
                pw_m = re.search(r'(?i)Password\s*:\s*([^\n\r]+)', block)

                if fn_m and ln_m and m_m and d_m and y_m and em_m and pw_m:
                    fn = fn_m.group(1).strip()
                    ln = ln_m.group(1).strip()
                    month = m_m.group(1).strip()
                    day = d_m.group(1).strip()
                    year = y_m.group(1).strip()
                    mail = em_m.group(1).strip()
                    pwd = pw_m.group(1).strip()

                    try:
                        await conn.execute("""
                            INSERT INTO task_stock (first_name, last_name, dob_month, dob_day, dob_year, email, password)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            ON CONFLICT (email) DO NOTHING
                        """, fn, ln, month, day, year, mail, pwd)
                        added += 1
                    except Exception:
                        pass
        else:
            lines = text.split("\n")
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 7:
                    fn, ln, month, day, year, mail, pwd = parts
                    try:
                        await conn.execute("""
                            INSERT INTO task_stock (first_name, last_name, dob_month, dob_day, dob_year, email, password)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            ON CONFLICT (email) DO NOTHING
                        """, fn, ln, month, day, year, mail, pwd)
                        added += 1
                    except Exception:
                        pass

    await message.answer(f"✅ Successfully added <b>{added}</b> profiles to active stock.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("rate_change_"))
async def adm_rate_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    r_type = call.data.split("_")[2]
    await state.update_data(target_rate_type=r_type)

    labels = {
        "readymade": "Readymade Accounts",
        "botdata": "Bot Task Accounts",
        "ref": "Referral Bonus"
    }
    await call.message.answer(f"⚙️ Enter new price rate for <b>{labels.get(r_type, r_type)}</b>:", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_new_rate)
    await call.answer()

@dp.message(AdminState.waiting_for_new_rate)
async def adm_rate_save(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    r_type = data.get("target_rate_type", "readymade")

    try:
        val = float(message.text.strip())
        key_map = {
            "readymade": "rate_readymade",
            "botdata": "rate_botdata",
            "ref": "ref_bonus"
        }
        await set_setting(key_map[r_type], val)
        
        labels = {
            "readymade": "Readymade Accounts",
            "botdata": "Bot Task Accounts",
            "ref": "Referral Bonus"
        }
        label_text = labels.get(r_type, "Accounts")
        
        broadcast_count = 0
        if r_type in ["readymade", "botdata"]:
            broadcast_count = await broadcast_price_update(label_text, val)

        await message.answer(
            f"✅ <b>Rate Updated!</b>\n"
            f"• Category: <b>{label_text}</b>\n"
            f"• New Rate: <b>₹{val:.2f}</b>\n"
            f"📢 Broadcast sent to <b>{broadcast_count}</b> users.",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Please provide a valid numerical amount.")
    await state.clear()

@dp.callback_query(F.data == "adm_add_bal")
async def adm_bal_id_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await call.message.answer("Enter target Telegram User ID:")
    await state.set_state(AdminState.waiting_for_addbal_id)
    await call.answer()

@dp.message(AdminState.waiting_for_addbal_id)
async def adm_bal_amt_prompt(message: types.Message, state: FSMContext):
    await state.update_data(target_uid=message.text.strip())
    await message.answer("Enter amount to credit or debit (e.g. <code>50</code> or <code>-20</code>):", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_addbal_amount)

@dp.message(AdminState.waiting_for_addbal_amount)
async def adm_bal_amt_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = int(data["target_uid"])
    amt = float(message.text.strip())

    await ensure_user(uid)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", amt, uid)

    await message.answer(f"✅ Balance adjusted for user <code>{uid}</code> by ₹{amt:.2f}.", parse_mode="HTML")
    await state.clear()

# ======================= WEB SERVER RUNNER & APP STARTUP =======================
async def handle_ping(request):
    return web.Response(text="GmailArena Bot Service Operational 24/7!")

async def main():
    if not DATABASE_URL:
        print("CRITICAL ERROR: DATABASE_URL missing!")
        return

    await init_db()

    # Launch background auto-expiry worker
    asyncio.create_task(task_expiry_worker())

    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🔥 Web Server bound to port {port}")
    print("🔥 PURGING TELEGRAM UPDATES QUEUE...")
    await bot.delete_webhook(drop_pending_updates=True)
    print("🔥 GMAILARENA BOT LIVE (TIMER + AUTO-RESTOCK + BAN SYSTEM) 🔥")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
