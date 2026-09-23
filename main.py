import os
import re
import random
import asyncio
import html
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
DATABASE_URL = os.environ.get("DATABASE_URL")
# =============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db_pool = None

# Strict UPI Regex Validator
UPI_REGEX = re.compile(r'^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$')

# ======================= DATABASE SETUP =======================
async def init_db():
    global db_pool
    clean_db_url = DATABASE_URL
    if clean_db_url and clean_db_url.startswith("postgres://"):
        clean_db_url = clean_db_url.replace("postgres://", "postgresql://", 1)
        
    db_pool = await asyncpg.create_pool(clean_db_url)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance NUMERIC(10, 2) DEFAULT 0.00,
                total_submitted INT DEFAULT 0,
                referred_by BIGINT DEFAULT NULL
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
                assigned_to BIGINT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                acc_type TEXT,
                email TEXT,
                password TEXT,
                recovery TEXT,
                two_fa TEXT,
                status TEXT DEFAULT 'pending',
                rejection_reason TEXT DEFAULT '',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                order_id TEXT UNIQUE,
                user_id BIGINT,
                amount NUMERIC(10, 2),
                upi_id TEXT,
                utr TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT INTO settings (key, value) VALUES ('rate_readymade', '12.0') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('rate_botdata', '15.0') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('ref_bonus', '1.0') ON CONFLICT (key) DO NOTHING;
        """)

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
                INSERT INTO users (user_id, username, balance, total_submitted, referred_by)
                VALUES ($1, $2, 0.00, 0, $3)
            """, user_id, username, ref)
        else:
            await conn.execute("UPDATE users SET username=$1 WHERE user_id=$2", username, user_id)

# ======================= FSM STATES =======================
class SubmitState(StatesGroup):
    choosing_type = State()
    waiting_for_email = State()
    waiting_for_password = State()
    waiting_for_recovery = State()
    waiting_for_2fa_choice = State()
    waiting_for_2fa_key = State()

class WithdrawState(StatesGroup):
    waiting_for_upi = State()

class AdminState(StatesGroup):
    waiting_for_bulk_stock = State()
    waiting_for_rate_type = State()
    waiting_for_new_rate = State()
    waiting_for_addbal_id = State()
    waiting_for_addbal_amount = State()
    waiting_for_custom_reject = State()
    waiting_for_utr = State()

# ======================= KEYBOARDS =======================
def main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡ Submit Gmail Account")],
            [KeyboardButton(text="💼 My Wallet"), KeyboardButton(text="📋 My Submissions")],
            [KeyboardButton(text="🤝 Affiliate & Earn"), KeyboardButton(text="📈 Live Stock")],
            [KeyboardButton(text="📢 Updates Channel"), KeyboardButton(text="🎧 24/7 Desk")]
        ],
        resize_keyboard=True
    )

def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Cancel Operation")]],
        resize_keyboard=True
    )

def sub_mode_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Submit Own Readymade"), KeyboardButton(text="📋 Generate Task Data")],
            [KeyboardButton(text="🚫 Cancel Operation")]
        ],
        resize_keyboard=True
    )

def recovery_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip Recovery Email")],
            [KeyboardButton(text="🚫 Cancel Operation")]
        ],
        resize_keyboard=True
    )

def two_factor_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔐 Add 2FA Secret Key")],
            [KeyboardButton(text="✓ Submit Without 2FA")],
            [KeyboardButton(text="🚫 Cancel Operation")]
        ],
        resize_keyboard=True
    )

# ======================= COMMAND HANDLERS =======================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    await ensure_user(user_id, username, referrer)

    r_ready = await get_setting("rate_readymade", 12.0)
    r_bot = await get_setting("rate_botdata", 15.0)

    welcome = (
        f"⚡ <b>Welcome to GmailArena Network, {html.escape(message.from_user.first_name)}!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Monetize verified Google accounts with automated instant payouts.\n\n"
        "💰 <b>Current Tier Rates:</b>\n"
        f"├ 📋 <b>Bot Assigned Tasks:</b> <b>₹{r_bot:.2f}</b> / acc\n"
        f"└ 📁 <b>Readymade Accounts:</b> <b>₹{r_ready:.2f}</b> / acc\n\n"
        "⏱ <b>Audit Window:</b> 24 – 72 Hours max\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose an action below to begin:"
    )
    await message.answer(welcome, parse_mode="HTML", reply_markup=main_reply_keyboard())

@dp.message(F.text == "🚫 Cancel Operation")
async def cancel_any_flow(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🔄 <b>Action cancelled.</b> Main dashboard ready.", parse_mode="HTML", reply_markup=main_reply_keyboard())

@dp.message(F.text == "📢 Updates Channel")
async def channel_info(message: types.Message):
    await message.answer(f"📢 <b>Official Telegram Network:</b>\n{CHANNEL_LINK}\n\nJoin for payment proofs and notices.", parse_mode="HTML")

@dp.message(F.text == "🎧 24/7 Desk")
async def support_info(message: types.Message):
    await message.answer(f"🎧 <b>Support Manager:</b>\nContact: {SUPPORT_USER}\nFast priority assistance.", parse_mode="HTML")

@dp.message(F.text == "📈 Live Stock")
async def stock_info(message: types.Message):
    stock_count = await get_available_stock_count()
    r_bot = await get_setting("rate_botdata", 15.0)
    await message.answer(
        f"📈 <b>Live Allocation Inventory:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Available Task Slots:</b> <b>{stock_count}</b> profiles ready\n"
        f"💵 <b>Current Yield:</b> ₹{r_bot:.2f} each\n\n"
        "<i>Slots update in real time. Choose '⚡ Submit Gmail Account' to lock your credentials.</i>",
        parse_mode="HTML"
    )

@dp.message(F.text == "🤝 Affiliate & Earn")
async def referral_dashboard(message: types.Message):
    user_id = message.from_user.id
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={user_id}"
    ref_bonus = await get_setting("ref_bonus", 1.0)

    async with db_pool.acquire() as conn:
        refs_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referred_by=$1", user_id)

    text = (
        "🤝 <b>Partner Affiliate Network</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Earn permanent rewards for inviting suppliers!\n\n"
        f"👥 <b>Your Referrals:</b> <b>{refs_count or 0}</b> active users\n"
        f"🎁 <b>Commission:</b> <b>₹{ref_bonus:.2f}</b> instant credit per approved account\n\n"
        "🔗 <b>Your Invite Link:</b>\n"
        f"<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# ======================= ADVANCED SUBMISSION HISTORY =======================
async def get_submissions_card(user_id: int):
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1", user_id)
        pending = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='pending'", user_id)
        approved = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='approved'", user_id)
        rejected = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='rejected'", user_id)
        
        # Pull last 10 submissions
        subs = await conn.fetch("""
            SELECT id, email, password, recovery, two_fa, status, rejection_reason, acc_type, created_at 
            FROM submissions WHERE user_id=$1 ORDER BY id DESC LIMIT 10
        """, user_id)

    card = (
        "📋 <b>Your Accounts Submission Console</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total Submitted : <b>{total or 0}</b>\n"
        f"⏳ In Audit Queue  : <b>{pending or 0}</b>\n"
        f"🟢 Approved        : <b>{approved or 0}</b>\n"
        f"🔴 Disqualified    : <b>{rejected or 0}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Recent Submissions (Last 10):</b>\n\n"
    )

    if not subs:
        card += "<i>No accounts submitted yet.</i>\n"
    else:
        for idx, row in enumerate(subs, 1):
            st = str(row['status']).lower()
            acc_type = "Task" if "Bot" in str(row['acc_type']) else "Ready"
            time_str = row['created_at'] or "Recently"
            
            card += f"<b>#{idx} • {html.escape(row['email'])}</b> [{acc_type}]\n"
            card += f"📅 Submitted: <code>{time_str}</code>\n"

            if st == "approved":
                # Data hidden on approval
                card += "🟢 Status: <b>✅ Verified & Paid</b>\n"
            elif st == "rejected":
                # Show credentials so user can inspect and discuss with support
                card += f"🔴 Status: <b>Disqualified</b>\n"
                card += f"⚠️ Reason: <i>{html.escape(row['rejection_reason'] or 'Invalid credentials')}</i>\n"
                card += f"🔑 Pass: <code>{html.escape(row['password'])}</code> | Rec: <code>{html.escape(row['recovery'])}</code>\n"
                if row['two_fa'] != 'None':
                    card += f"🔐 2FA: <code>{html.escape(row['two_fa'])}</code>\n"
            else:
                # Pending: show credentials
                card += "⏳ Status: <b>In Review</b>\n"
                card += f"🔑 Pass: <code>{html.escape(row['password'])}</code> | Rec: <code>{html.escape(row['recovery'])}</code>\n"
                if row['two_fa'] != 'None':
                    card += f"🔐 2FA: <code>{html.escape(row['two_fa'])}</code>\n"
            
            card += "────────────────────────\n"

    refresh_btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Refresh Queue Status", callback_data="reload_history")
    ]])
    return card, refresh_btn

@dp.message(F.text == "📋 My Submissions")
async def submissions_view(message: types.Message):
    card, kb = await get_submissions_card(message.from_user.id)
    await message.answer(card, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "reload_history")
async def submissions_reload(call: types.CallbackQuery):
    card, kb = await get_submissions_card(call.from_user.id)
    try:
        await call.message.edit_text(card, parse_mode="HTML", reply_markup=kb)
        await call.answer("Submissions queue refreshed!")
    except Exception:
        await call.answer("Queue is currently up to date.")

# ======================= ADVANCED WALLET & WITHDRAWALS =======================
@dp.message(F.text == "💼 My Wallet")
async def wallet_view(message: types.Message):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or message.from_user.first_name)

    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0

    r1 = await get_setting("rate_readymade", 12.0)
    r2 = await get_setting("rate_botdata", 15.0)
    min_p = min(r1, r2)

    text = (
        "💼 <b>Vault Financial Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Available Balance:</b> <b>₹{balance:.2f}</b>\n"
        f"💳 <b>Minimum Cashout:</b> ₹{min_p:.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Instant settlement via direct UPI transfer."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Request Cashout (UPI)", callback_data="claim_funds")],
        [InlineKeyboardButton(text="📜 View Payout History", callback_data="view_payout_history")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "view_payout_history")
async def payout_history_view(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with db_pool.acquire() as conn:
        payouts = await conn.fetch("""
            SELECT order_id, amount, upi_id, utr, status, created_at 
            FROM withdrawals WHERE user_id=$1 ORDER BY id DESC LIMIT 10
        """, user_id)

    text = (
        "📜 <b>Settlement & Payout Invoices</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not payouts:
        text += "<i>No withdrawal requests found.</i>\n"
    else:
        for p in payouts:
            st = str(p['status']).lower()
            badge = "🟢 PAID" if st == "paid" else "⏳ PENDING"
            text += f"<b>Order:</b> <code>{p['order_id']}</code>\n"
            text += f"💵 Amount: <b>₹{float(p['amount']):.2f}</b>\n"
            text += f"📱 UPI: <code>{html.escape(p['upi_id'])}</code>\n"
            text += f"📅 Date: {p['created_at'] or 'Recent'}\n"
            text += f"🏷 Status: <b>{badge}</b>\n"
            if p['utr']:
                text += f"🧾 UTR/Ref: <code>{html.escape(p['utr'])}</code>\n"
            text += "────────────────────────\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Back to Wallet", callback_data="back_to_wallet")
    ]])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "back_to_wallet")
async def back_to_wallet_call(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0

    r1 = await get_setting("rate_readymade", 12.0)
    r2 = await get_setting("rate_botdata", 15.0)
    min_p = min(r1, r2)

    text = (
        "💼 <b>Vault Financial Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Available Balance:</b> <b>₹{balance:.2f}</b>\n"
        f"💳 <b>Minimum Cashout:</b> ₹{min_p:.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Instant settlement via direct UPI transfer."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Request Cashout (UPI)", callback_data="claim_funds")],
        [InlineKeyboardButton(text="📜 View Payout History", callback_data="view_payout_history")]
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "claim_funds")
async def initiate_cashout(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0

    r1 = await get_setting("rate_readymade", 12.0)
    r2 = await get_setting("rate_botdata", 15.0)
    min_p = min(r1, r2)

    if balance < min_p:
        await call.answer(f"Minimum threshold is ₹{min_p:.2f}. Your balance is ₹{balance:.2f}.", show_alert=True)
        return

    await call.message.answer(
        "📱 <b>Enter your Official UPI ID for payout:</b>\n"
        "<i>Valid Handles: @ybl, @ibl, @paytm, @okaxis, @okhdfcbank, @oksbi, @fam, etc.</i>\n\n"
        "<b>Example:</b> <code>rajesh98@okaxis</code> or <code>9876543210@paytm</code>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(WithdrawState.waiting_for_upi)
    await call.answer()

@dp.message(WithdrawState.waiting_for_upi)
async def process_cashout_target(message: types.Message, state: FSMContext):
    upi = message.text.strip().lower()

    # Strict UPI Validation
    if not UPI_REGEX.match(upi) or " " in upi:
        await message.answer(
            "⚠️ <b>Invalid UPI ID Structure!</b>\n"
            "Please provide a valid address with handles like <code>@okaxis</code>, <code>@paytm</code>, <code>@ybl</code>, <code>@oksbi</code>.\n\n"
            "Try again or press <b>🚫 Cancel Operation</b>:",
            parse_mode="HTML"
        )
        return

    user_id = message.from_user.id
    # Generate unique bot order ID
    order_id = f"GA-W-{random.randint(10000, 99999)}"
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0
        
        if balance <= 0:
            await message.answer("⚠️ Insufficient balance for cashout.", reply_markup=main_reply_keyboard())
            await state.clear()
            return

        await conn.execute("UPDATE users SET balance=0.00 WHERE user_id=$1", user_id)
        w_id = await conn.fetchval("""
            INSERT INTO withdrawals (order_id, user_id, amount, upi_id, status, created_at)
            VALUES ($1, $2, $3, $4, 'pending', $5) RETURNING id
        """, order_id, user_id, balance, upi, now_str)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 Mark Paid & Enter UTR", callback_data=f"startpay_{w_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 <b>New Cashout Order: {order_id}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User: @{message.from_user.username} (ID: <code>{user_id}</code>)\n"
            f"💵 Amount: <b>₹{balance:.2f}</b>\n"
            f"📱 Target UPI: <code>{html.escape(upi)}</code>\n"
            f"📅 Placed: {now_str}"
        ),
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    await message.answer(
        f"✅ <b>Withdrawal Order #{order_id} Created!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Payout Amount : <b>₹{balance:.2f}</b>\n"
        f"📱 Transfer UPI  : <code>{html.escape(upi)}</code>\n"
        "⏳ Status        : <b>Processing Settlement</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "You can track this request in <b>💼 My Wallet ➔ Payout History</b>.",
        parse_mode="HTML",
        reply_markup=main_reply_keyboard()
    )
    await state.clear()

# ======================= ADMIN PAYOUT WITH UTR FLOW =======================
@dp.callback_query(F.data.startswith("startpay_"))
async def admin_pay_request_utr(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    w_id = int(call.data.split("_")[1])
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT order_id, amount, upi_id, status FROM withdrawals WHERE id=$1", w_id)
        if not row or row['status'] != 'pending':
            await call.answer("This withdrawal is already processed!", show_alert=True)
            return

    await state.update_data(target_wid=w_id, wid_card_msg_id=call.message.message_id)
    await call.message.reply(
        f"🧾 <b>Enter the UTR / Bank Reference Number for #{row['order_id']}:</b>\n"
        f"Amount: ₹{float(row['amount']):.2f} ➔ UPI: <code>{row['upi_id']}</code>\n\n"
        "Send reference number below:",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.waiting_for_utr)
    await call.answer()

@dp.message(AdminState.waiting_for_utr)
async def admin_save_utr_and_settle(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    utr_code = message.text.strip()
    data = await state.get_data()
    w_id = data.get("target_wid")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT order_id, user_id, amount, upi_id FROM withdrawals WHERE id=$1", w_id)
        if row:
            order_id = row['order_id']
            uid = row['user_id']
            amount = float(row['amount'])
            upi = row['upi_id']
            
            await conn.execute("UPDATE withdrawals SET status='paid', utr=$1 WHERE id=$2", utr_code, w_id)

            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"🎉 <b>Settlement Completed & Dispatched!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 Order ID   : <b>{order_id}</b>\n"
                        f"💵 Transferred: <b>₹{amount:.2f}</b>\n"
                        f"📱 Bank UPI   : <code>{html.escape(upi)}</code>\n"
                        f"🔗 UTR/Ref No : <code>{html.escape(utr_code)}</code>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "Funds should reflect in your bank account immediately."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Error notifying user: {e}")

    await message.answer(f"✅ Order <b>{order_id}</b> settled with UTR: <code>{utr_code}</code>", parse_mode="HTML")
    await state.clear()

# ======================= ACCOUNT SUBMISSION WORKFLOW =======================
@dp.message(F.text == "⚡ Submit Gmail Account")
async def start_submission_prompt(message: types.Message, state: FSMContext):
    r_ready = await get_setting("rate_readymade", 12.0)
    r_bot = await get_setting("rate_botdata", 15.0)

    text = (
        "⚡ <b>Choose Task Protocol:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>✍️ Submit Own Readymade (₹{r_ready:.2f}):</b>\n"
        "• Submit pre-created Gmail accounts.\n"
        "• Must be active, healthy, and accessible.\n\n"
        f"2️⃣ <b>📋 Generate Task Data (₹{r_bot:.2f}):</b>\n"
        "• We provide pre-allocated Name, DOB & Password.\n"
        "• Register the Gmail using exact bot credentials.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select your method below:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=sub_mode_keyboard())
    await state.set_state(SubmitState.choosing_type)

@dp.message(SubmitState.choosing_type, F.text == "✍️ Submit Own Readymade")
async def mode_readymade_selected(message: types.Message, state: FSMContext):
    r_ready = await get_setting("rate_readymade", 12.0)
    await state.update_data(acc_type="Readymade")
    msg = (
        "📁 <b>Readymade Account Submission</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Reward:</b> ₹{r_ready:.2f} per verified account\n\n"
        "📧 <b>Enter the Gmail Address:</b>\n"
        "<i>(e.g. <code>username88@gmail.com</code>)</i>"
    )
    await message.answer(msg, parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(SubmitState.waiting_for_email)

@dp.message(SubmitState.choosing_type, F.text == "📋 Generate Task Data")
async def mode_botdata_selected(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    r_bot = await get_setting("rate_botdata", 15.0)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, first_name, last_name, dob_month, dob_day, dob_year, email, password 
            FROM task_stock WHERE status='available' LIMIT 1
        """)
        if not row:
            await message.answer(
                "⚠️ <b>Inventory Exhausted!</b>\nAll bot data tasks are claimed right now. Please use 'Submit Own Readymade' or wait for restock.",
                parse_mode="HTML",
                reply_markup=main_reply_keyboard()
            )
            await state.clear()
            return
        
        stock_id = row['id']
        await conn.execute("UPDATE task_stock SET status='assigned', assigned_to=$1 WHERE id=$2", user_id, stock_id)

    await state.update_data(acc_type="Bot-Data Task")
    task_card = (
        f"📋 <b>Target Registration Credentials:</b>\n"
        f"💰 Payout: <b>₹{r_bot:.2f}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• First Name: <code>{html.escape(row['first_name'])}</code>\n"
        f"• Last Name: <code>{html.escape(row['last_name'])}</code>\n"
        f"• Birthday: <code>{html.escape(row['dob_month'])} {html.escape(str(row['dob_day']))}, {html.escape(str(row['dob_year']))}</code>\n"
        f"• Suggested Email: <code>{html.escape(row['email'])}</code>\n"
        f"• Password: <code>{html.escape(row['password'])}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 <b>Strict Notice:</b> Use the exact credentials above, otherwise payment will be rejected.\n\n"
        "➡️ <b>Once created, enter the registered Email Address below:</b>"
    )
    await message.answer(task_card, parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(SubmitState.waiting_for_email)

@dp.message(SubmitState.waiting_for_email)
async def process_sub_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if "@gmail.com" not in email.lower():
        await message.answer("⚠️ <b>Invalid Email:</b> Must end with <code>@gmail.com</code>. Try again:", parse_mode="HTML")
        return
    await state.update_data(email=email)
    await message.answer("🔑 <b>Enter the Password for this account:</b>", parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(SubmitState.waiting_for_password)

@dp.message(SubmitState.waiting_for_password)
async def process_sub_password(message: types.Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await message.answer(
        "🛡 <b>Recovery Email Check:</b>\n"
        "If you linked a recovery address, send it below. Otherwise, tap <b>Skip</b>.",
        parse_mode="HTML",
        reply_markup=recovery_keyboard()
    )
    await state.set_state(SubmitState.waiting_for_recovery)

@dp.message(SubmitState.waiting_for_recovery, F.text == "⏭ Skip Recovery Email")
async def skip_recovery_step(message: types.Message, state: FSMContext):
    await state.update_data(recovery="None")
    await prompt_2fa_step(message, state)

@dp.message(SubmitState.waiting_for_recovery)
async def receive_recovery_step(message: types.Message, state: FSMContext):
    await state.update_data(recovery=message.text.strip())
    await prompt_2fa_step(message, state)

async def prompt_2fa_step(message: types.Message, state: FSMContext):
    await message.answer(
        "🔐 <b>Two-Factor Authentication (2FA):</b>\n"
        "Attaching 2FA keys speeds up verification queue.\nSelect an option:",
        parse_mode="HTML",
        reply_markup=two_factor_keyboard()
    )
    await state.set_state(SubmitState.waiting_for_2fa_choice)

@dp.message(SubmitState.waiting_for_2fa_choice, F.text == "✓ Submit Without 2FA")
async def finalize_no_2fa(message: types.Message, state: FSMContext):
    await state.update_data(two_fa="None")
    await complete_submission(message, state)

@dp.message(SubmitState.waiting_for_2fa_choice, F.text == "🔐 Add 2FA Secret Key")
async def request_2fa_key(message: types.Message, state: FSMContext):
    await message.answer(
        "🔑 <b>Paste your 2FA Secret Key / Backup code below:</b>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(SubmitState.waiting_for_2fa_key)

@dp.message(SubmitState.waiting_for_2fa_key)
async def finalize_with_2fa(message: types.Message, state: FSMContext):
    await state.update_data(two_fa=message.text.strip())
    await complete_submission(message, state)

async def complete_submission(message: types.Message, state: FSMContext):
    data = await state.get_data()
    acc_type = data["acc_type"]
    email = data["email"]
    pwd = data["password"]
    rec = data["recovery"]
    two_fa = data["two_fa"]
    user = message.from_user
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    await ensure_user(user.id, user.username or user.first_name)

    async with db_pool.acquire() as conn:
        sub_id = await conn.fetchval("""
            INSERT INTO submissions (user_id, acc_type, email, password, recovery, two_fa, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7) RETURNING id
        """, user.id, acc_type, email, pwd, rec, two_fa, now_str)
        await conn.execute("UPDATE users SET total_submitted = total_submitted + 1 WHERE user_id=$1", user.id)

    r_est = await (get_setting("rate_botdata", 15.0) if "Bot" in acc_type else get_setting("rate_readymade", 12.0))

    admin_panel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Approve (+₹{r_est:.2f})", callback_data=f"adm_app_{sub_id}"),
        InlineKeyboardButton(text="❌ Reject Task", callback_data=f"adm_rejmenu_{sub_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📥 <b>Submission Queue Item #{sub_id}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User: @{user.username} (ID: <code>{user.id}</code>)\n"
            f"🏷 Type: <b>{acc_type}</b> (Reward: ₹{r_est:.2f})\n\n"
            f"📧 Email: <code>{html.escape(email)}</code>\n"
            f"🔑 Password: <code>{html.escape(pwd)}</code>\n"
            f"🛡 Recovery: <code>{html.escape(rec)}</code>\n"
            f"🔐 2FA Key: <code>{html.escape(two_fa)}</code>\n"
            f"📅 Submitted: {now_str}"
        ),
        parse_mode="HTML",
        reply_markup=admin_panel_kb
    )

    confirm_card = (
        "✅ <b>Account Successfully Received!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📧 Account : <code>{html.escape(email)}</code>\n"
        f"💵 Payout  : <b>₹{r_est:.2f}</b> (On verification)\n"
        "⏳ Status  : <b>🟡 In Review Queue</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Track live progress anytime inside <b>📋 My Submissions</b>."
    )
    await message.answer(confirm_card, parse_mode="HTML", reply_markup=main_reply_keyboard())
    await state.clear()

# ======================= ADMIN VERIFICATION ACTIONS =======================
@dp.callback_query(F.data.startswith("adm_app_"))
async def admin_accept_sub(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[2])

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, email, status, acc_type FROM submissions WHERE id=$1", sub_id)
        if not row or str(row['status']).lower() != "pending":
            await call.answer("This task has already been processed!", show_alert=True)
            return

        uid = int(row['user_id'])
        mail = row['email']
        acc_type = row['acc_type']
        reward = await (get_setting("rate_botdata", 15.0) if "Bot" in str(acc_type) else get_setting("rate_readymade", 12.0))

        await conn.execute("UPDATE submissions SET status='approved' WHERE id=$1", sub_id)
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", reward, uid)
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)

        # Referral commission bonus
        referrer = await conn.fetchval("SELECT referred_by FROM users WHERE user_id=$1", uid)
        if referrer:
            ref_bonus = await get_setting("ref_bonus", 1.0)
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", ref_bonus, referrer)
            try:
                await bot.send_message(
                    chat_id=referrer,
                    text=f"🎁 <b>Affiliate Bonus!</b> You earned <b>₹{ref_bonus:.2f}</b> from a referral submission."
                )
            except Exception:
                pass

    try:
        await bot.send_message(
            chat_id=uid,
            text=(
                f"🎉 <b>Account Verified & Approved!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📧 Account: <code>{html.escape(mail)}</code>\n"
                f"💵 Reward Added: <b>+₹{reward:.2f}</b>\n"
                f"💼 Updated Balance: <b>₹{float(new_bal):.2f}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "You can withdraw your funds in <b>💼 My Wallet</b>!"
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
            await call.answer("This task is already processed!", show_alert=True)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Incorrect Password", callback_data=f"rjact_{sub_id}_Wrong Password")],
        [InlineKeyboardButton(text="🔒 2FA / Phone Lock Triggered", callback_data=f"rjact_{sub_id}_2FA / Phone Lock")],
        [InlineKeyboardButton(text="⚠️ Account Suspended / Flagged", callback_data=f"rjact_{sub_id}_Account Flagged")],
        [InlineKeyboardButton(text="✏️ Custom Reason (Type)", callback_data=f"rjcustom_{sub_id}")],
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
        InlineKeyboardButton(text="❌ Reject Task", callback_data=f"adm_rejmenu_{sub_id}")
    ]])
    await call.message.edit_reply_markup(reply_markup=restore_kb)
    await call.answer()

@dp.callback_query(F.data.startswith("rjact_"))
async def admin_reject_quick(call: types.CallbackQuery):
    parts = call.data.split("_", 2)
    sub_id = int(parts[1])
    reason = parts[2]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, email, status FROM submissions WHERE id=$1", sub_id)
        if not row or str(row['status']).lower() != "pending":
            await call.answer("This task is already processed!", show_alert=True)
            return

        uid = int(row['user_id'])
        mail = row['email']
        await conn.execute("UPDATE submissions SET status='rejected', rejection_reason=$1 WHERE id=$2", reason, sub_id)

    try:
        await bot.send_message(
            chat_id=uid,
            text=(
                f"🔴 <b>Submission Disqualified</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📧 Account: <code>{html.escape(mail)}</code>\n"
                f"⚠️ Reason: <b>{html.escape(reason)}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Please verify login credentials and submit fresh tasks."
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Error notifying: {e}")

    await call.message.edit_text(f"{call.message.text}\n\n🔴 <b>STATUS: REJECTED ({html.escape(reason)})</b>", parse_mode="HTML")
    await call.answer("Rejected.")

@dp.callback_query(F.data.startswith("rjcustom_"))
async def admin_reject_custom_start(call: types.CallbackQuery, state: FSMContext):
    sub_id = int(call.data.split("_")[1])
    await state.update_data(target_sub_id=sub_id)
    await call.message.reply(f"✏️ <b>Send custom rejection reason for #{sub_id}:</b>", parse_mode="HTML")
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
        row = await conn.fetchrow("SELECT user_id, email FROM submissions WHERE id=$1", sub_id)
        if row:
            uid = int(row['user_id'])
            mail = row['email']
            await conn.execute("UPDATE submissions SET status='rejected', rejection_reason=$1 WHERE id=$2", reason, sub_id)
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"🔴 <b>Submission Disqualified</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📧 Account: <code>{html.escape(mail)}</code>\n"
                        f"⚠️ Reason: <b>{html.escape(reason)}</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "Check details in <b>📋 My Submissions</b>."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await message.answer(f"✅ Disqualified #{sub_id} with reason: <b>{html.escape(reason)}</b>", parse_mode="HTML")
    await state.clear()

# ======================= COMPLETE ADMIN PANEL =======================
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
            InlineKeyboardButton(text=f"⚙️ Readymade (₹{r_ready:.2f})", callback_data="rate_change_readymade"),
            InlineKeyboardButton(text=f"⚙️ Bot Tasks (₹{r_bot:.2f})", callback_data="rate_change_botdata")
        ],
        [
            InlineKeyboardButton(text=f"🎁 Affiliate Bonus (₹{r_ref:.2f})", callback_data="rate_change_ref"),
            InlineKeyboardButton(text="💳 Adjust Balance", callback_data="adm_add_bal")
        ]
    ])

    card = (
        "👑 <b>Executive Admin Terminal</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Active Users      : <b>{total_users or 0}</b>\n"
        f"📦 Available Stock   : <b>{stock_count}</b> slots\n"
        f"⏳ Pending Audits    : <b>{pending_subs or 0}</b>\n"
        f"💸 Pending Payouts   : <b>{pending_payouts or 0}</b>\n\n"
        "💰 <b>Active Unit Rates:</b>\n"
        f"• Readymade Accounts : ₹{r_ready:.2f}\n"
        f"• Bot Allocation Tasks: ₹{r_bot:.2f}\n"
        f"• Referral Bonus     : ₹{r_ref:.2f}"
    )
    await message.answer(card, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "adm_upload_stock")
async def adm_stock_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    msg = (
        "📥 <b>Upload Structured Task Data:</b>\n\n"
        "Format per line:\n"
        "<code>FirstName|LastName|Month|Day|Year|Email|Password</code>\n\n"
        "<b>Example:</b>\n"
        "<code>David|Miller|August|19|1992|davidm92@gmail.com|Kx928shH!2</code>\n\n"
        "Send your batch now:"
    )
    await call.message.answer(msg, parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_bulk_stock)
    await call.answer()

@dp.message(AdminState.waiting_for_bulk_stock)
async def adm_stock_process(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    lines = message.text.strip().split("\n")
    added = 0

    async with db_pool.acquire() as conn:
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 7:
                fn, ln, month, day, year, mail, pwd = parts
                try:
                    await conn.execute("""
                        INSERT INTO task_stock (first_name, last_name, dob_month, dob_day, dob_year, email, password)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """, fn, ln, month, day, year, mail, pwd)
                    added += 1
                except Exception:
                    pass

    await message.answer(f"✅ Successfully added <b>{added}</b> profiles into stock.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("rate_change_"))
async def adm_rate_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    r_type = call.data.split("_")[2]
    await state.update_data(target_rate_type=r_type)
    
    labels = {
        "readymade": "Readymade Accounts",
        "botdata": "Bot Allocation Tasks",
        "ref": "Affiliate Commission per Account"
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
        await message.answer(f"✅ Rate updated to <b>₹{val:.2f}</b> successfully.", parse_mode="HTML")
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

# ======================= NATIVE HTTP WEB SERVER =======================
async def handle_ping(request):
    return web.Response(text="GmailArena Bot Service is 100% Operational 24/7!")

async def main():
    await init_db()

    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🔥 Web Server bound to port {port}")
    print("🔥 GMAILARENA COMPLETE ENTERPRISE BOT ACTIVE 🔥")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
