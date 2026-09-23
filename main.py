import asyncio
import html
import os
import sqlite3
import threading
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from flask import Flask

# ======================= FLASK DUMMY SERVER =======================
web_app = Flask(__name__)


@web_app.route("/")
def home():
  return "Gmail Seller Bot is Active 24/7!"


def run_flask():
  port = int(os.environ.get("PORT", 10000))
  web_app.run(host="0.0.0.0", port=port)


# ======================= CONFIGURATION =======================
BOT_TOKEN = "8822939259:AAGxqsUpMXIs1U01PAKkLJcCWqzHblf6Uog"
ADMIN_ID = 5834588787
CHANNEL_LINK = "https://t.me/Gmail_arena"
SUPPORT_USER = "@sxhivv"
# =============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ======================= DATABASE SETUP =======================
DB_PATH = "gmail_bot.db"


def get_db():
  conn = sqlite3.connect(DB_PATH, check_same_thread=False)
  conn.execute("PRAGMA journal_mode=WAL;")
  return conn


init_conn = get_db()
init_cur = init_conn.cursor()

init_cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance REAL DEFAULT 0.0,
    total_submitted INTEGER DEFAULT 0
)
""")

init_cur.execute("""
CREATE TABLE IF NOT EXISTS task_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    dob_month TEXT,
    dob_day TEXT,
    dob_year TEXT,
    email TEXT UNIQUE,
    password TEXT,
    status TEXT DEFAULT 'available',
    assigned_to INTEGER DEFAULT NULL
)
""")

init_cur.execute("""
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    acc_type TEXT,
    email TEXT,
    password TEXT,
    recovery TEXT,
    two_fa TEXT,
    status TEXT DEFAULT 'pending',
    rejection_reason TEXT DEFAULT ''
)
""")

init_cur.execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    upi_id TEXT,
    status TEXT DEFAULT 'pending'
)
""")

init_cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

init_cur.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_readymade',"
    " '12.0')"
)
init_cur.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_botdata',"
    " '15.0')"
)
init_conn.commit()
init_conn.close()


def get_rate(rate_type="readymade"):
  conn = get_db()
  cur = conn.cursor()
  key = "rate_readymade" if rate_type == "readymade" else "rate_botdata"
  cur.execute("SELECT value FROM settings WHERE key=?", (key,))
  row = cur.fetchone()
  conn.close()
  return float(row[0]) if row else 15.0


def set_rate(rate_type, new_rate):
  conn = get_db()
  cur = conn.cursor()
  key = "rate_readymade" if rate_type == "readymade" else "rate_botdata"
  cur.execute(
      "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
      (key, str(new_rate)),
  )
  conn.commit()
  conn.close()


def get_min_payout():
  return min(get_rate("readymade"), get_rate("botdata"))


def get_available_stock_count():
  conn = get_db()
  cur = conn.cursor()
  cur.execute("SELECT COUNT(*) FROM task_stock WHERE status='available'")
  count = cur.fetchone()[0]
  conn.close()
  return count


def ensure_user(user_id: int, username: str = ""):
  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      """
        INSERT INTO users (user_id, username, balance, total_submitted)
        VALUES (?, ?, 0.0, 0)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
    """,
      (user_id, username),
  )
  conn.commit()
  conn.close()


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
          [
              KeyboardButton(text="💼 My Wallet"),
              KeyboardButton(text="📊 Submission History"),
          ],
          [
              KeyboardButton(text="📢 Official Channel"),
              KeyboardButton(text="💬 24/7 Support"),
          ],
      ],
      resize_keyboard=True,
  )


# ======================= BASIC HANDLERS =======================
@dp.message(Command("start"))
async def start_handler(message: types.Message):
  user_id = message.from_user.id
  username = message.from_user.username or message.from_user.first_name
  ensure_user(user_id, username)

  rate_ready = get_rate("readymade")
  rate_bot = get_rate("botdata")

  text = (
      f"✨ <b>Welcome, {html.escape(message.from_user.first_name)}!</b>\n"
      "─────────────────────────\n"
      "Earn money instantly by providing verified Google accounts.\n\n"
      "💎 <b>Current Payout Rates:</b>\n"
      f"├ 📋 <b>Bot Task Creation:</b> ₹{rate_bot:.2f}\n"
      f"└ 📁 <b>Readymade Accounts:</b> ₹{rate_ready:.2f}\n\n"
      "⏱ <b>Audit Window:</b> 24 – 72 Hours Max\n"
      "─────────────────────────\n"
      "Choose an action below to start earning:"
  )
  await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu())


@dp.message(F.text == "📢 Official Channel")
async def updates_handler(message: types.Message):
  await message.answer(
      f"📢 <b>Official News & Payment Proofs:</b>\n{CHANNEL_LINK}",
      parse_mode="HTML",
      disable_web_page_preview=True,
  )


@dp.message(F.text == "💬 24/7 Support")
async def support_handler(message: types.Message):
  await message.answer(
      f"💬 <b>Direct Support Manager:</b>\nReach out to {SUPPORT_USER} for fast"
      " assistance.",
      parse_mode="HTML",
  )


# ======================= SUBMISSIONS STATUS PAGE =======================
@dp.message(F.text.in_({"📊 Submission History", "📊 My Submissions"}))
async def submissions_status_page(message: types.Message):
  user_id = message.from_user.id
  conn = get_db()
  cur = conn.cursor()

  cur.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=?", (user_id,)
  )
  total = cur.fetchone()[0]

  cur.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=? AND LOWER(status) ="
      " 'pending'",
      (user_id,),
  )
  pending = cur.fetchone()[0]

  cur.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=? AND LOWER(status) ="
      " 'approved'",
      (user_id,),
  )
  approved = cur.fetchone()[0]

  cur.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=? AND LOWER(status) ="
      " 'rejected'",
      (user_id,),
  )
  rejected = cur.fetchone()[0]

  cur.execute(
      "SELECT email, status, rejection_reason, acc_type FROM submissions WHERE"
      " user_id=? ORDER BY id DESC LIMIT 10",
      (user_id,),
  )
  recent_subs = cur.fetchall()
  conn.close()

  text = "📊 <b>Account Submission History</b>\n"
  text += "─────────────────────────\n"
  text += f"📦 <b>Total Submitted:</b> {total}\n"
  text += f"⏳ <b>Pending Review:</b> {pending}\n"
  text += f"🟢 <b>Approved:</b> {approved}\n"
  text += f"🔴 <b>Rejected:</b> {rejected}\n"
  text += "─────────────────────────\n"
  text += "📋 <b>Recent Submissions (Last 10):</b>\n\n"

  if not recent_subs:
    text += "<i>No submissions recorded yet.</i>\n"
  else:
    for s_mail, s_status, s_reason, s_type in recent_subs:
      st = str(s_status).lower()
      type_tag = "Task" if "Bot" in str(s_type) else "Ready"
      if st == "approved":
        tag = "🟢 Approved"
      elif st == "rejected":
        tag = f"🔴 Rejected ({html.escape(s_reason)})" if s_reason else "🔴 Rejected"
      else:
        tag = "🟡 In Review"
      text += f"• <code>{html.escape(s_mail)}</code> [{type_tag}] ➔ {tag}\n"

  await message.answer(text, parse_mode="HTML")


# ======================= WALLET DASHBOARD =======================
@dp.message(F.text == "💼 My Wallet")
async def wallet_dashboard(message: types.Message):
  user_id = message.from_user.id
  username = message.from_user.username or message.from_user.first_name
  ensure_user(user_id, username)

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT COALESCE(balance, 0.0) FROM users WHERE user_id=?", (user_id,)
  )
  user_row = cur.fetchone()
  balance = float(user_row[0]) if user_row else 0.0
  min_payout = get_min_payout()

  cur.execute(
      "SELECT amount, upi_id, status FROM withdrawals WHERE user_id=? ORDER BY"
      " id DESC LIMIT 3",
      (user_id,),
  )
  withdrawals = cur.fetchall()
  conn.close()

  text = "💼 <b>Financial Wallet Dashboard</b>\n"
  text += "─────────────────────────\n"
  text += f"💵 <b>Available Balance:</b> ₹{balance:.2f}\n"
  text += f"💳 <b>Minimum Cashout:</b> ₹{min_payout:.2f}\n"
  text += "─────────────────────────\n"
  text += "💸 <b>Recent Payout Invoices:</b>\n"

  if not withdrawals:
    text += "<i>No withdrawal requests on file.</i>\n"
  else:
    for w_amt, w_upi, w_status in withdrawals:
      w_tag = (
          "🟢 Settled"
          if str(w_status).lower() == "paid"
          else "🟡 Processing"
      )
      text += (
          f"• ₹{w_amt:.2f} ➔ <code>{html.escape(w_upi)}</code> [{w_tag}]\n"
      )

  kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="⚡ Request Payout Now", callback_data="start_withdraw"
          )
      ]]
  )

  await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "start_withdraw")
async def start_withdrawal_flow(call: types.CallbackQuery, state: FSMContext):
  user_id = call.from_user.id
  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT COALESCE(balance, 0.0) FROM users WHERE user_id=?", (user_id,)
  )
  row = cur.fetchone()
  conn.close()

  balance = float(row[0]) if row else 0.0
  min_payout = get_min_payout()

  if balance < min_payout:
    await call.answer(
        f"Minimum payout is ₹{min_payout:.2f}. Your balance is ₹{balance:.2f}.",
        show_alert=True,
    )
    return

  await call.message.answer(
      "📱 <b>Enter your UPI ID / Address:</b>\n<i>(e.g."
      " <code>developer@upi</code> / <code>9876543210@paytm</code>)</i>",
      parse_mode="HTML",
  )
  await state.set_state(WithdrawState.waiting_for_upi)
  await call.answer()


@dp.message(WithdrawState.waiting_for_upi)
async def process_withdrawal_request(message: types.Message, state: FSMContext):
  upi = message.text.strip()
  user_id = message.from_user.id

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT COALESCE(balance, 0.0) FROM users WHERE user_id=?", (user_id,)
  )
  balance = float(cur.fetchone()[0])

  cur.execute("UPDATE users SET balance=0.0 WHERE user_id=?", (user_id,))
  cur.execute(
      "INSERT INTO withdrawals (user_id, amount, upi_id, status) VALUES (?,"
      " ?, ?, 'pending')",
      (user_id, balance, upi),
  )
  w_id = cur.lastrowid
  conn.commit()
  conn.close()

  admin_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="💸 Confirm & Mark Paid",
              callback_data=f"paid_{w_id}_{user_id}",
          )
      ]]
  )

  await bot.send_message(
      chat_id=ADMIN_ID,
      text=(
          f"🔔 <b>New Payout Order #{w_id}</b>\n"
          "─────────────────────────\n"
          f"👤 User: @{message.from_user.username} (ID: <code>{user_id}</code>)\n"
          f"💵 Cashout Amount: <b>₹{balance:.2f}</b>\n"
          f"📱 Transfer UPI: <code>{html.escape(upi)}</code>"
      ),
      parse_mode="HTML",
      reply_markup=admin_kb,
  )

  await message.answer(
      "✅ <b>Payout Request Dispatched!</b>\nYour payment has entered the"
      " settlement queue. Check status anytime in <b>💼 My Wallet</b>.",
      parse_mode="HTML",
  )
  await state.clear()


@dp.callback_query(F.data.startswith("paid_"))
async def mark_payout_complete(call: types.CallbackQuery):
  _, w_id, uid = call.data.split("_")
  w_id, uid = int(w_id), int(uid)

  conn = get_db()
  cur = conn.cursor()
  cur.execute("SELECT amount FROM withdrawals WHERE id=?", (w_id,))
  amt_row = cur.fetchone()
  amt = float(amt_row[0]) if amt_row else 0.0

  cur.execute("UPDATE withdrawals SET status='paid' WHERE id=?", (w_id,))
  conn.commit()
  conn.close()

  try:
    await bot.send_message(
        chat_id=uid,
        text=(
            f"🎉 <b>Payout Sent Successfully!</b>\nYour payment of"
            f" <b>₹{amt:.2f}</b> has been transferred to your UPI account."
        ),
        parse_mode="HTML",
    )
  except:
    pass

  await call.message.edit_text(
      f"{call.message.text}\n\n🟢 <b>STATUS: PAID & SETTLED</b>",
      parse_mode="HTML",
  )
  await call.answer("Payout completed!")


# ======================= SUBMISSION SELECTION =======================
@dp.message(F.text.in_({"⚡ Submit Accounts", "⚡ Submit Gmail Tasks"}))
async def choose_submission_mode(message: types.Message):
  rate_ready = get_rate("readymade")
  rate_bot = get_rate("botdata")

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text=f"📋 Create From Bot Data (₹{rate_bot:.2f})",
                  callback_data="mode_botdata",
              )
          ],
          [
              InlineKeyboardButton(
                  text=f"📁 Submit Readymade (₹{rate_ready:.2f})",
                  callback_data="mode_readymade",
              )
          ],
      ]
  )
  text = (
      "⚡ <b>Select Task Submission Model:</b>\n"
      "─────────────────────────\n"
      f"1️⃣ <b>Bot Data Creation</b> — <b>₹{rate_bot:.2f} / account</b>\n"
      "• We provide First/Last Name, DOB, and Credentials.\n"
      "• High approval rate when registered precisely.\n\n"
      f"2️⃣ <b>Readymade Account</b> — <b>₹{rate_ready:.2f} / account</b>\n"
      "• Directly submit pre-created active accounts.\n"
      "• Must have clean security status.\n"
      "─────────────────────────\n"
      "Tap an option to proceed:"
  )
  await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "mode_readymade")
async def start_readymade_flow(call: types.CallbackQuery, state: FSMContext):
  rate_ready = get_rate("readymade")
  await state.update_data(acc_type="Readymade")

  msg = (
      "📁 <b>Readymade Account Submission</b>\n"
      "─────────────────────────\n"
      f"💰 <b>Reward:</b> ₹{rate_ready:.2f} per verified account\n\n"
      "🛡 <b>Quality Guidelines:</b>\n"
      "• Accounts must not be flagged, locked, or phone-locked.\n"
      "• Provide accurate passwords.\n\n"
      "📧 <b>Send your Gmail address below:</b>\n"
      "<i>(e.g. <code>myaccount@gmail.com</code>)</i>"
  )
  await call.message.answer(msg, parse_mode="HTML")
  await state.set_state(SubmitState.waiting_for_email)
  await call.answer()


@dp.callback_query(F.data == "mode_botdata")
async def start_botdata_flow(call: types.CallbackQuery, state: FSMContext):
  user_id = call.from_user.id
  rate_bot = get_rate("botdata")

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT id, first_name, last_name, dob_month, dob_day, dob_year, email,"
      " password FROM task_stock WHERE status='available' LIMIT 1"
  )
  item = cur.fetchone()

  if not item:
    conn.close()
    await call.message.answer(
        "⚠️ <b>Allocations Temporarily Empty!</b>\nAll bot-data tasks are"
        " currently claimed. Our team is restocking shortly.",
        parse_mode="HTML",
    )
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🚨 <b>STOCK ALERT:</b> Stock is 0! Restock via /admin to keep"
            " users creating accounts."
        ),
        parse_mode="HTML",
    )
    await call.answer()
    return

  stock_id, fn, ln, month, day, year, email, password = item

  cur.execute(
      "UPDATE task_stock SET status='assigned', assigned_to=? WHERE id=?",
      (user_id, stock_id),
  )
  conn.commit()
  conn.close()

  await state.update_data(acc_type="Bot-Data Task")

  task_msg = (
      f"💰 <b>Reward:</b> ₹{rate_bot:.2f} per verified account\n\n"
      f"First name: {html.escape(fn)}\n"
      f"Last name: {html.escape(ln)}\n"
      "----------\n"
      "Date of birth\n"
      f"Month: {html.escape(month)} | Day: {html.escape(str(day))} | Year:"
      f" {html.escape(str(year))}\n"
      "----------\n"
      f"Email: {html.escape(email)}\n"
      "----------\n"
      f"Password: {html.escape(password)}\n"
      "----------\n"
      "🔒 <b>Be sure to use the specified data, otherwise the account will not"
      " be paid.</b>\n\n"
      "➡️ <b>Once created, send that Email Address here to proceed:</b>"
  )
  await call.message.answer(task_msg, parse_mode="HTML")
  await state.set_state(SubmitState.waiting_for_email)
  await call.answer()


@dp.message(SubmitState.waiting_for_email)
async def process_sub_email(message: types.Message, state: FSMContext):
  email = message.text.strip()
  if "@gmail.com" not in email.lower():
    await message.answer(
        "⚠️ <b>Invalid Email:</b> Must be a valid address ending with"
        " <code>@gmail.com</code>.",
        parse_mode="HTML",
    )
    return
  await state.update_data(email=email)
  await message.answer(
      "🔑 Enter the <b>Password</b> for this account:", parse_mode="HTML"
  )
  await state.set_state(SubmitState.waiting_for_password)


@dp.message(SubmitState.waiting_for_password)
async def process_sub_password(message: types.Message, state: FSMContext):
  await state.update_data(password=message.text.strip())

  skip_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="⏭ Skip Recovery", callback_data="skip_rec"
          )
      ]]
  )
  await message.answer(
      "🛡 <b>Recovery Email Attached?</b>\nSend it now, or tap <b>Skip</b>.",
      parse_mode="HTML",
      reply_markup=skip_kb,
  )
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
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🔐 Provide 2FA Key (High Priority)",
                  callback_data="2fa_yes",
              )
          ],
          [
              InlineKeyboardButton(
                  text="⏩ Submit Without 2FA", callback_data="2fa_no"
              )
          ],
      ]
  )
  await msg_obj.answer(
      "🔐 <b>Two-Factor Authentication (2FA):</b>\nProviding 2FA keys speeds up"
      " review drastically.",
      parse_mode="HTML",
      reply_markup=kb,
  )
  await state.set_state(SubmitState.waiting_for_2fa_choice)


@dp.callback_query(F.data == "2fa_no", SubmitState.waiting_for_2fa_choice)
async def sub_no_2fa(call: types.CallbackQuery, state: FSMContext):
  await state.update_data(two_fa="None")
    
