import os
import asyncio
import html
from aiohttp import web
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
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

# ======================= CLOUD DB INITIALIZATION =======================
async def init_db():
    global db_pool
    # Clean connection URL for asyncpg
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
                total_submitted INT DEFAULT 0
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
                rejection_reason TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount NUMERIC(10, 2),
                upi_id TEXT,
                status TEXT DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT INTO settings (key, value) VALUES ('rate_readymade', '12.0') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('rate_botdata', '15.0') ON CONFLICT (key) DO NOTHING;
        """)

async def get_rate(rate_type="readymade"):
    key = "rate_readymade" if rate_type == "readymade" else "rate_botdata"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return float(row['value']) if row else 15.0

async def set_rate(rate_type, new_rate):
    key = "rate_readymade" if rate_type == "readymade" else "rate_botdata"
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = $2
        """, key, str(new_rate))

async def get_min_payout():
    r1 = await get_rate("readymade")
    r2 = await get_rate("botdata")
    return min(r1, r2)

async def get_available_stock_count():
    async with db_pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM task_stock WHERE status='available'")
        return val or 0

async def ensure_user(user_id: int, username: str = ""):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, balance, total_submitted)
            VALUES ($1, $2, 0.00, 0)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
        """, user_id, username)

# ======================= FSM STATES =======================
class SubmitState(StatesGroup):
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

# ======================= KEYBOARDS =======================
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡ Submit Accounts")],
            [KeyboardButton(text="💼 My Wallet"), KeyboardButton(text="📊 Submission History")],
            [KeyboardButton(text="📢 Official Channel"), KeyboardButton(text="💬 24/7 Support")]
        ],
        resize_keyboard=True
    )

# ======================= BASIC HANDLERS =======================
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    await ensure_user(user_id, username)

    rate_ready = await get_rate("readymade")
    rate_bot = await get_rate("botdata")

    text = (
        f"✨ <b>Welcome, {html.escape(message.from_user.first_name)}!</b>\n"
        f"─────────────────────────\n"
        f"Earn money by providing verified Google accounts.\n\n"
        f"💎 <b>Current Payout Rates:</b>\n"
        f"├ 📋 <b>Bot Task Creation:</b> ₹{rate_bot:.2f}\n"
        f"└ 📁 <b>Readymade Accounts:</b> ₹{rate_ready:.2f}\n\n"
        f"⏱ <b>Audit Window:</b> 24 – 72 Hours Max\n"
        f"─────────────────────────\n"
        f"Choose an action below to start earning:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu())

@dp.message(F.text == "📢 Official Channel")
async def updates_handler(message: types.Message):
    await message.answer(
        f"📢 <b>Official Channel:</b>\n{CHANNEL_LINK}",
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@dp.message(F.text == "💬 24/7 Support")
async def support_handler(message: types.Message):
    await message.answer(f"💬 <b>Direct Support:</b> Contact {SUPPORT_USER}", parse_mode="HTML")

# ======================= HISTORY WITH REFRESH =======================
async def build_history_text(user_id: int):
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1", user_id)
        pending = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='pending'", user_id)
        approved = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='approved'", user_id)
        rejected = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE user_id=$1 AND LOWER(status)='rejected'", user_id)
        recent_subs = await conn.fetch("SELECT email, status, rejection_reason, acc_type FROM submissions WHERE user_id=$1 ORDER BY id DESC LIMIT 10", user_id)

    text = "📊 <b>Account Submission History</b>\n"
    text += "─────────────────────────\n"
    text += f"📦 <b>Total Submitted:</b> {total or 0}\n"
    text += f"⏳ <b>Pending Review:</b> {pending or 0}\n"
    text += f"🟢 <b>Approved:</b> {approved or 0}\n"
    text += f"🔴 <b>Rejected:</b> {rejected or 0}\n"
    text += "─────────────────────────\n"
    text += "📋 <b>Recent Submissions (Last 10):</b>\n\n"

    if not recent_subs:
        text += "<i>No submissions recorded yet.</i>\n"
    else:
        for row in recent_subs:
            st = str(row['status']).lower()
            type_tag = "Task" if "Bot" in str(row['acc_type']) else "Ready"
            if st == "approved":
                tag = "🟢 Approved"
            elif st == "rejected":
                tag = f"🔴 Rejected ({html.escape(row['rejection_reason'])})" if row['rejection_reason'] else "🔴 Rejected"
            else:
                tag = "🟡 In Review"
            text += f"• <code>{html.escape(row['email'])}</code> [{type_tag}] ➔ {tag}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Refresh List", callback_data="refresh_history")
    ]])
    return text, kb

@dp.message(F.text.in_({"📊 Submission History", "📊 My Submissions"}))
async def submissions_status_page(message: types.Message):
    text, kb = await build_history_text(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "refresh_history")
async def refresh_history_callback(call: types.CallbackQuery):
    text, kb = await build_history_text(call.from_user.id)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await call.answer("History updated!")
    except Exception:
        await call.answer("Already up to date!")

# ======================= WALLET DASHBOARD =======================
@dp.message(F.text == "💼 My Wallet")
async def wallet_dashboard(message: types.Message):
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username or message.from_user.first_name)

    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0
        withdrawals = await conn.fetch("SELECT amount, upi_id, status FROM withdrawals WHERE user_id=$1 ORDER BY id DESC LIMIT 3", user_id)

    min_payout = await get_min_payout()
    text = "💼 <b>Financial Wallet Dashboard</b>\n"
    text += "─────────────────────────\n"
    text += f"💵 <b>Available Balance:</b> ₹{balance:.2f}\n"
    text += f"💳 <b>Minimum Cashout:</b> ₹{min_payout:.2f}\n"
    text += "─────────────────────────\n"
    text += "💸 <b>Recent Payout Invoices:</b>\n"

    if not withdrawals:
        text += "<i>No withdrawal requests on file.</i>\n"
    else:
        for row in withdrawals:
            w_tag = "🟢 Settled" if str(row['status']).lower() == "paid" else "🟡 Processing"
            text += f"• ₹{float(row['amount']):.2f} ➔ <code>{html.escape(row['upi_id'])}</code> [{w_tag}]\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚡ Request Payout Now", callback_data="start_withdraw")
    ]])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "start_withdraw")
async def start_withdrawal_flow(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0

    min_payout = await get_min_payout()
    if balance < min_payout:
        await call.answer(f"Minimum payout is ₹{min_payout:.2f}. Your balance is ₹{balance:.2f}.", show_alert=True)
        return

    await call.message.answer("📱 <b>Enter your UPI ID:</b>\n<i>(e.g. <code>someone@okaxis</code>)</i>", parse_mode="HTML")
    await state.set_state(WithdrawState.waiting_for_upi)
    await call.answer()

@dp.message(WithdrawState.waiting_for_upi)
async def process_withdrawal_request(message: types.Message, state: FSMContext):
    upi = message.text.strip()
    user_id = message.from_user.id

    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", user_id)
        balance = float(bal) if bal is not None else 0.0
        await conn.execute("UPDATE users SET balance=0.00 WHERE user_id=$1", user_id)
        w_id = await conn.fetchval("""
            INSERT INTO withdrawals (user_id, amount, upi_id, status)
            VALUES ($1, $2, $3, 'pending') RETURNING id
        """, user_id, balance, upi)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 Confirm & Mark Paid", callback_data=f"paid_{w_id}_{user_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 <b>New Payout Order #{w_id}</b>\n"
            f"─────────────────────────\n"
            f"👤 User: @{message.from_user.username} (ID: <code>{user_id}</code>)\n"
            f"💵 Cashout Amount: <b>₹{balance:.2f}</b>\n"
            f"📱 Transfer UPI: <code>{html.escape(upi)}</code>"
        ),
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    await message.answer("✅ <b>Payout Request Dispatched!</b>\nCheck status anytime in <b>💼 My Wallet</b>.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("paid_"))
async def mark_payout_complete(call: types.CallbackQuery):
    _, w_id, uid = call.data.split("_")
    w_id, uid = int(w_id), int(uid)

    async with db_pool.acquire() as conn:
        amt = await conn.fetchval("SELECT amount FROM withdrawals WHERE id=$1", w_id)
        amount = float(amt) if amt is not None else 0.0
        await conn.execute("UPDATE withdrawals SET status='paid' WHERE id=$1", w_id)

    try:
        await bot.send_message(
            chat_id=uid,
            text=f"🎉 <b>Payout Sent Successfully!</b>\nYour payout of <b>₹{amount:.2f}</b> has been transferred to your UPI account.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Error notifying payout: {e}")

    await call.message.edit_text(f"{call.message.text}\n\n🟢 <b>STATUS: PAID & SETTLED</b>", parse_mode="HTML")
    await call.answer("Payout completed!")

# ======================= ACCOUNT SUBMISSIONS =======================
@dp.message(F.text.in_({"⚡ Submit Accounts", "⚡ Submit Gmail Tasks"}))
async def choose_submission_mode(message: types.Message):
    rate_ready = await get_rate("readymade")
    rate_bot = await get_rate("botdata")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📋 Create From Bot Data (₹{rate_bot:.2f})", callback_data="mode_botdata")],
        [InlineKeyboardButton(text=f"📁 Submit Readymade (₹{rate_ready:.2f})", callback_data="mode_readymade")]
    ])
    text = (
        "⚡ <b>Select Task Submission Model:</b>\n"
        "─────────────────────────\n"
        f"1️⃣ <b>Bot Data Creation</b> — <b>₹{rate_bot:.2f} / account</b>\n"
        "• We provide First/Last Name, DOB, and Credentials.\n\n"
        f"2️⃣ <b>Readymade Account</b> — <b>₹{rate_ready:.2f} / account</b>\n"
        "• Submit existing active Gmail accounts directly.\n"
        "─────────────────────────\n"
        "Tap an option to proceed:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "mode_readymade")
async def start_readymade_flow(call: types.CallbackQuery, state: FSMContext):
    rate_ready = await get_rate("readymade")
    await state.update_data(acc_type="Readymade")

    msg = (
        "📁 <b>Readymade Account Submission</b>\n"
        "─────────────────────────\n"
        f"💰 <b>Reward:</b> ₹{rate_ready:.2f} per verified account\n\n"
        "📧 <b>Send your Gmail address below:</b>\n"
        "<i>(e.g. <code>myaccount@gmail.com</code>)</i>"
    )
    await call.message.answer(msg, parse_mode="HTML")
    await state.set_state(SubmitState.waiting_for_email)
    await call.answer()

@dp.callback_query(F.data == "mode_botdata")
async def start_botdata_flow(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    rate_bot = await get_rate("botdata")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, first_name, last_name, dob_month, dob_day, dob_year, email, password FROM task_stock WHERE status='available' LIMIT 1")
        if not row:
            await call.message.answer(
                "⚠️ <b>Allocations Temporarily Empty!</b>\nAll bot-data tasks are claimed. Our team is restocking shortly.",
                parse_mode="HTML"
            )
            await bot.send_message(
                chat_id=ADMIN_ID,
                text="🚨 <b>STOCK ALERT:</b> Stock is 0! Restock via /admin.",
                parse_mode="HTML"
            )
            await call.answer()
            return
        
        stock_id = row['id']
        await conn.execute("UPDATE task_stock SET status='assigned', assigned_to=$1 WHERE id=$2", user_id, stock_id)

    await state.update_data(acc_type="Bot-Data Task")
    task_msg = (
        f"💰 <b>Reward:</b> ₹{rate_bot:.2f} per verified account\n\n"
        f"First name: {html.escape(row['first_name'])}\n"
        f"Last name: {html.escape(row['last_name'])}\n"
        f"----------\n"
        f"Date of birth\n"
        f"Month: {html.escape(row['dob_month'])} | Day: {html.escape(str(row['dob_day']))} | Year: {html.escape(str(row['dob_year']))}\n"
        f"----------\n"
        f"Email: {html.escape(row['email'])}\n"
        f"----------\n"
        f"Password: {html.escape(row['password'])}\n"
        f"----------\n"
        f"🔒 <b>Be sure to use the specified data, otherwise the account will not be paid.</b>\n\n"
        f"➡️ <b>Once created, send that Email Address here to proceed:</b>"
    )
    await call.message.answer(task_msg, parse_mode="HTML")
    await state.set_state(SubmitState.waiting_for_email)
    await call.answer()

@dp.message(SubmitState.waiting_for_email)
async def process_sub_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if "@gmail.com" not in email.lower():
        await message.answer("⚠️ <b>Invalid Email:</b> Must end with <code>@gmail.com</code>.", parse_mode="HTML")
        return
    await state.update_data(email=email)
    await message.answer("🔑 Enter the <b>Password</b> for this account:", parse_mode="HTML")
    await state.set_state(SubmitState.waiting_for_password)

@dp.message(SubmitState.waiting_for_password)
async def process_sub_password(message: types.Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Skip Recovery", callback_data="skip_rec")
    ]])
    await message.answer("🛡 <b>Recovery Email Attached?</b>\nSend it now, or tap <b>Skip</b>.", parse_mode="HTML", reply_markup=skip_kb)
    await state.set_state(SubmitState.waiting_for_recovery)

@dp.message(SubmitState.waiting_for_recovery)
async def process_sub_rec_text(message: types.Message, state: FSMContext):
    await state.update_data(recovery=message.text.strip())
    await prompt_2fa(message, state)

@dp.callback_query(F.data == "skip_rec", SubmitState.waiting_for_recovery)
async def process_sub_skip_rec(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(recovery="None")
    await prompt_2fa(call.message, state)
    await call.answer()

async def prompt_2fa(msg_obj, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Provide 2FA Key (High Priority)", callback_data="2fa_yes")],
        [InlineKeyboardButton(text="⏩ Submit Without 2FA", callback_data="2fa_no")]
    ])
    await msg_obj.answer("🔐 <b>Two-Factor Authentication (2FA):</b>\nAttaching 2FA keys speeds up audit.", parse_mode="HTML", reply_markup=kb)
    await state.set_state(SubmitState.waiting_for_2fa_choice)

@dp.callback_query(F.data == "2fa_no", SubmitState.waiting_for_2fa_choice)
async def sub_no_2fa(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(two_fa="None")
    await finalize_submission(call.message, call.from_user, state)
    await call.answer()

@dp.callback_query(F.data == "2fa_yes", SubmitState.waiting_for_2fa_choice)
async def sub_yes_2fa(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("🔑 Paste your <b>2FA Secret Key / Backup Code</b>:", parse_mode="HTML")
    await state.set_state(SubmitState.waiting_for_2fa_key)
    await call.answer()

@dp.message(SubmitState.waiting_for_2fa_key)
async def sub_process_2fa_key(message: types.Message, state: FSMContext):
    await state.update_data(two_fa=message.text.strip())
    await finalize_submission(message, message.from_user, state)

async def finalize_submission(msg_obj, user, state: FSMContext):
    data = await state.get_data()
    acc_type = data["acc_type"]
    email = data["email"]
    pwd = data["password"]
    rec = data["recovery"]
    two_fa = data["two_fa"]

    await ensure_user(user.id, user.username or user.first_name)

    async with db_pool.acquire() as conn:
        sub_id = await conn.fetchval("""
            INSERT INTO submissions (user_id, acc_type, email, password, recovery, two_fa, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending') RETURNING id
        """, user.id, acc_type, email, pwd, rec, two_fa)
        await conn.execute("UPDATE users SET total_submitted = total_submitted + 1 WHERE user_id=$1", user.id)

    rate_preview = await (get_rate("botdata") if "Bot" in acc_type else get_rate("readymade"))

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Approve (+₹{rate_preview:.2f})", callback_data=f"adm_app_{sub_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rejmenu_{sub_id}")
    ]])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📥 <b>New Submission #{sub_id}</b>\n"
            f"─────────────────────────\n"
            f"👤 User: @{user.username} (ID: <code>{user.id}</code>)\n"
            f"🏷 Type: <b>{acc_type}</b> (Reward: ₹{rate_preview:.2f})\n\n"
            f"📧 Email: <code>{html.escape(email)}</code>\n"
            f"🔑 Password: <code>{html.escape(pwd)}</code>\n"
            f"🛡 Recovery: <code>{html.escape(rec)}</code>\n"
            f"🔐 2FA: <code>{html.escape(two_fa)}</code>"
        ),
        parse_mode="HTML",
        reply_markup=admin_kb
    )

    view_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📊 View in History", callback_data="refresh_history")
    ]])

    await msg_obj.answer(
        "✅ <b>Account Submitted Successfully!</b>\n\n"
        "Status: 🟡 <b>In Review</b>\n"
        "Review Window: 24 to 72 Hours\n\n"
        "Track your submission anytime in <b>📊 Submission History</b>.",
        parse_mode="HTML",
        reply_markup=view_kb
    )
    await state.clear()

# ======================= ADMIN ACTIONS =======================
@dp.callback_query(F.data.startswith("adm_app_"))
async def admin_approve_submission(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[2])

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, email, status, acc_type FROM submissions WHERE id=$1", sub_id)
        if not row or str(row['status']).lower() != "pending":
            await call.answer("This task is already processed!", show_alert=True)
            return

        uid = int(row['user_id'])
        mail = row['email']
        acc_type = row['acc_type']
        reward = await (get_rate("botdata") if "Bot" in str(acc_type) else get_rate("readymade"))

        await conn.execute("UPDATE submissions SET status='approved' WHERE id=$1", sub_id)
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", reward, uid)
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)

    try:
        await bot.send_message(
            chat_id=uid,
            text=(
                f"🎉 <b>Account Verified & Approved!</b>\n"
                f"─────────────────────────\n"
                f"📧 Account: <code>{html.escape(mail)}</code>\n"
                f"💵 Added: <b>+₹{reward:.2f}</b>\n"
                f"💼 Total Balance: <b>₹{float(new_bal):.2f}</b>\n"
                f"─────────────────────────\n"
                f"Ready for cashout in <b>💼 My Wallet</b>!"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Notification error: {e}")

    await call.message.edit_text(f"{call.message.text}\n\n🟢 <b>STATUS: APPROVED (+₹{reward:.2f})</b>", parse_mode="HTML")
    await call.answer(f"Approved! +₹{reward:.2f} credited.")

@dp.callback_query(F.data.startswith("adm_rejmenu_"))
async def admin_reject_menu_switch(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[2])
    async with db_pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM submissions WHERE id=$1", sub_id)
        if not st or str(st).lower() != "pending":
            await call.answer("This task has already been processed!", show_alert=True)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Wrong Password", callback_data=f"rjaction_{sub_id}_Wrong Password")],
        [InlineKeyboardButton(text="🔒 2FA / OTP Verification Locked", callback_data=f"rjaction_{sub_id}_2FA Locked")],
        [InlineKeyboardButton(text="⚠️ Account Disabled / Suspended", callback_data=f"rjaction_{sub_id}_Account Disabled")],
        [InlineKeyboardButton(text="✏️ Type Custom Reason", callback_data=f"rjcustom_{sub_id}")],
        [InlineKeyboardButton(text="🔙 Cancel", callback_data=f"rjcancel_{sub_id}")]
    ])
    await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("rjcancel_"))
async def admin_reject_cancel(call: types.CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    rate_preview = await get_rate("readymade")

    restore_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Approve (+₹{rate_preview:.2f})", callback_data=f"adm_app_{sub_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rejmenu_{sub_id}")
    ]])
    await call.message.edit_reply_markup(reply_markup=restore_kb)
    await call.answer()

@dp.callback_query(F.data.startswith("rjaction_"))
async def admin_reject_execute(call: types.CallbackQuery):
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
                f"🔴 <b>Submission Rejected</b>\n"
                f"─────────────────────────\n"
                f"📧 Account: <code>{html.escape(mail)}</code>\n"
                f"⚠️ Reason: <b>{html.escape(reason)}</b>\n"
                f"─────────────────────────\n"
                f"Please check credentials and submit fresh tasks."
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Notification error: {e}")

    await call.message.edit_text(f"{call.message.text}\n\n🔴 <b>STATUS: REJECTED ({html.escape(reason)})</b>", parse_mode="HTML")
    await call.answer("Rejected with reason recorded.")

@dp.callback_query(F.data.startswith("rjcustom_"))
async def admin_reject_custom_prompt(call: types.CallbackQuery, state: FSMContext):
    sub_id = int(call.data.split("_")[1])
    await state.update_data(target_sub_id=sub_id)
    await call.message.reply(f"✏️ <b>Type rejection reason for #{sub_id}:</b>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_custom_reject)
    await call.answer()

@dp.message(AdminState.waiting_for_custom_reject)
async def admin_reject_custom_save(message: types.Message, state: FSMContext):
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
                        f"🔴 <b>Submission Rejected</b>\n"
                        f"─────────────────────────\n"
                        f"📧 Account: <code>{html.escape(mail)}</code>\n"
                        f"⚠️ Reason: <b>{html.escape(reason)}</b>\n"
                        f"─────────────────────────\n"
                        f"Check status anytime in <b>📊 Submission History</b>."
                    ),
                    parse_mode="HTML"
                )
            except:
                pass

    await message.answer(f"✅ Task #{sub_id} rejected with reason: <b>{html.escape(reason)}</b>", parse_mode="HTML")
    await state.clear()

# ======================= ADMIN MASTER PANEL =======================
@dp.message(Command("admin"))
async def admin_control_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        pending_subs = await conn.fetchval("SELECT COUNT(*) FROM submissions WHERE LOWER(status)='pending'")

    available_stock = await get_available_stock_count()
    r_ready = await get_rate("readymade")
    r_bot = await get_rate("botdata")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Upload Task Stock", callback_data="adm_upload_stock")],
        [
            InlineKeyboardButton(text=f"⚙️ Readymade Rate (₹{r_ready:.2f})", callback_data="rate_change_readymade"),
            InlineKeyboardButton(text=f"⚙️ Bot-Data Rate (₹{r_bot:.2f})", callback_data="rate_change_botdata")
        ],
        [InlineKeyboardButton(text="💳 Balance Adjustment", callback_data="adm_add_bal")]
    ])

    dashboard = (
        f"👑 <b>Executive Admin Terminal</b>\n"
        f"─────────────────────────\n"
        f"👥 <b>Total Platform Users:</b> {total_users or 0}\n"
        f"📦 <b>Bot Stock Remaining:</b> {available_stock}\n"
        f"⏳ <b>Pending Audits:</b> {pending_subs or 0}\n\n"
        f"💰 <b>Active Unit Rates:</b>\n"
        f"• 📁 Readymade: ₹{r_ready:.2f}\n"
        f"• 📋 Bot Task: ₹{r_bot:.2f}"
    )
    await message.answer(dashboard, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "adm_upload_stock")
async def adm_upload_stock_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    msg = (
        "📥 <b>Upload Structured Task Data:</b>\n\n"
        "Format (one entry per line):\n"
        "<code>FirstName|LastName|Month|Day|Year|Email|Password</code>\n\n"
        "<b>Example:</b>\n"
        "<code>John|Krum|July|12|1986|johnkrum623@gmail.com|9VQZqgHRv6WU</code>\n\n"
        "Paste your batch below:"
    )
    await call.message.answer(msg, parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_bulk_stock)
    await call.answer()

@dp.message(AdminState.waiting_for_bulk_stock)
async def adm_process_bulk_stock(message: types.Message, state: FSMContext):
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

    await message.answer(f"✅ Successfully added <b>{added}</b> profiles to available stock.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("rate_change_"))
async def adm_rate_change_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    rate_type = call.data.split("_")[2]
    label = "Readymade Accounts" if rate_type == "readymade" else "Bot-Data Tasks"
    await state.update_data(target_rate_type=rate_type)
    await call.message.answer(f"⚙️ Enter new price rate for <b>{label}</b>:", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_new_rate)
    await call.answer()

@dp.message(AdminState.waiting_for_new_rate)
async def adm_process_new_rate(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    rate_type = data.get("target_rate_type", "readymade")

    try:
        val = float(message.text.strip())
        await set_rate(rate_type, val)
        label = "Readymade Accounts" if rate_type == "readymade" else "Bot-Data Tasks"
        await message.answer(f"✅ Rate for <b>{label}</b> updated to <b>₹{val:.2f}</b>.", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Please enter a valid number.")
    await state.clear()

@dp.callback_query(F.data == "adm_add_bal")
async def adm_add_balance_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await call.message.answer("Enter target Telegram User ID:")
    await state.set_state(AdminState.waiting_for_addbal_id)
    await call.answer()

@dp.message(AdminState.waiting_for_addbal_id)
async def adm_process_addbal_uid(message: types.Message, state: FSMContext):
    await state.update_data(target_uid=message.text.strip())
    await message.answer("Enter amount to add or deduct (e.g. <code>50</code> or <code>-20</code>):", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_addbal_amount)

@dp.message(AdminState.waiting_for_addbal_amount)
async def adm_process_addbal_amt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = int(data["target_uid"])
    amt = float(message.text.strip())

    await ensure_user(uid)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", amt, uid)

    await message.answer(f"✅ Balance for User <code>{uid}</code> adjusted by ₹{amt:.2f}.", parse_mode="HTML")
    await state.clear()

# ======================= NATIVE HTTP SERVER & RUNNER =======================
async def handle_ping(request):
    return web.Response(text="Gmail Seller Bot is Active 24/7!")

async def main():
    await init_db()

    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🔥 Native Web Server running on port {port}")
    print("🔥 GMAIL SELLER BOT LIVE (POSTGRES CONNECTED) 🔥")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
