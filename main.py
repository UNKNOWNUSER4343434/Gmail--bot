import asyncio
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

# Default dual rates
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
          [KeyboardButton(text="⚡ Submit Gmail Tasks")],
          [
              KeyboardButton(text="💼 My Wallet"),
              KeyboardButton(text="📊 My Submissions"),
          ],
          [
              KeyboardButton(text="📢 Updates Channel"),
              KeyboardButton(text="🛠 24/7 Support"),
          ],
      ],
      resize_keyboard=True,
  )


# ======================= BASIC HANDLERS =======================
@dp.message(Command("start"))
async def start_handler(message: types.Message):
  user_id = message.from_user.id
  username = message.from_user.username or message.from_user.first_name

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
      (user_id, username),
  )
  conn.commit()
  conn.close()

  rate_ready = get_rate("readymade")
  rate_bot = get_rate("botdata")

  welcome_text = (
      f"👋 <b>Welcome, {message.from_user.first_name}!</b>\n\n"
      "⚡ <b>Current Earning Rates:</b>\n"
      f"• 📋 <b>Bot Data Creation:</b> ₹{rate_bot:.2f} / account\n"
      f"• 📁 <b>Readymade Account:</b> ₹{rate_ready:.2f} / account\n\n"
      "⏱ <b>Verification Period:</b> 24 to 72 Hours max\n\n"
      "Select an option below to get started."
  )
  await message.answer(
      welcome_text, parse_mode="HTML", reply_markup=get_main_menu()
  )


@dp.message(F.text == "📢 Updates Channel")
async def updates_handler(message: types.Message):
  await message.answer(
      f"📢 <b>Official Channel:</b>\nJoin here: {CHANNEL_LINK}",
      parse_mode="HTML",
      disable_web_page_preview=True,
  )


@dp.message(F.text == "🛠 24/7 Support")
async def support_handler(message: types.Message):
  await message.answer(
      f"🛠 <b>Customer Support:</b>\nFor any inquiries or issues, contact:"
      f" {SUPPORT_USER}",
      parse_mode="HTML",
  )


# ======================= SUBMISSIONS STATUS PAGE =======================
@dp.message(F.text == "📊 My Submissions")
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

  text = "📊 <b>Your Account Submissions</b>\n"
  text += "━━━━━━━━━━━━━━━━━━━━━━\n"
  text += f"📦 <b>Total Accounts Sent:</b> {total}\n"
  text += f"⏳ <b>Pending Review:</b> {pending}\n"
  text += f"✅ <b>Approved:</b> {approved}\n"
  text += f"❌ <b>Rejected:</b> {rejected}\n\n"
  text += "📋 <b>Recent Submissions (Last 10):</b>\n"

  if not recent_subs:
    text += "<i>No submissions found yet.</i>\n"
  else:
    for s_mail, s_status, s_reason, s_type in recent_subs:
      st = str(s_status).lower()
      type_label = "Bot Data" if "Bot" in str(s_type) else "Readymade"
      if st == "approved":
        tag = "✅ Approved"
      elif st == "rejected":
        tag = f"❌ Rejected ({s_reason})" if s_reason else "❌ Rejected"
      else:
        tag = "⏳ Pending"
      text += f"• <code>{s_mail}</code> [{type_label}] ➔ {tag}\n"

  await message.answer(text, parse_mode="HTML")


# ======================= WALLET DASHBOARD =======================
@dp.message(F.text == "💼 My Wallet")
async def wallet_dashboard(message: types.Message):
  user_id = message.from_user.id
  conn = get_db()
  cur = conn.cursor()
  cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
  user_row = cur.fetchone()
  balance = user_row[0] if user_row else 0.0
  min_payout = get_min_payout()

  cur.execute(
      "SELECT amount, upi_id, status FROM withdrawals WHERE user_id=? ORDER BY"
      " id DESC LIMIT 3",
      (user_id,),
  )
  withdrawals = cur.fetchall()
  conn.close()

  text = "💼 <b>My Wallet Dashboard</b>\n"
  text += "━━━━━━━━━━━━━━━━━━━━━━\n"
  text += f"💵 <b>Available Balance:</b> ₹{balance:.2f}\n"
  text += f"💳 <b>Minimum Withdrawal:</b> ₹{min_payout:.2f}\n\n"

  text += "💸 <b>Recent Payout Requests:</b>\n"
  if not withdrawals:
    text += "<i>No withdrawal requests yet.</i>\n"
  else:
    for w_amt, w_upi, w_status in withdrawals:
      w_tag = (
          "✅ Paid" if str(w_status).lower() == "paid" else "⏳ Pending Review"
      )
      text += f"• ₹{w_amt:.2f} via <code>{w_upi}</code> ➔ {w_tag}\n"

  kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="💸 Request Withdrawal", callback_data="start_withdraw"
          )
      ]]
  )

  await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "start_withdraw")
async def start_withdrawal_flow(call: types.CallbackQuery, state: FSMContext):
  user_id = call.from_user.id
  conn = get_db()
  cur = conn.cursor()
  cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
  row = cur.fetchone()
  conn.close()

  balance = row[0] if row else 0.0
  min_payout = get_min_payout()

  if balance < min_payout:
    await call.answer(
        f"Minimum payout threshold is ₹{min_payout:.2f}. Your balance is"
        f" ₹{balance:.2f}.",
        show_alert=True,
    )
    return

  await call.message.answer(
      "📱 <b>Enter your UPI ID:</b>\n<i>(Example:"
      " <code>someone@okaxis</code>)</i>",
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
  cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
  balance = cur.fetchone()[0]

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
              text="💸 Mark as Paid", callback_data=f"paid_{w_id}_{user_id}"
          )
      ]]
  )

  await bot.send_message(
      chat_id=ADMIN_ID,
      text=(
          f"🔔 <b>New Withdrawal Request #{w_id}</b>\n\n"
          f"👤 User: @{message.from_user.username} (ID: <code>{user_id}</code>)\n"
          f"💵 Amount: <b>₹{balance:.2f}</b>\n"
          f"📱 UPI Address: <code>{upi}</code>"
      ),
      parse_mode="HTML",
      reply_markup=admin_kb,
  )

  await message.answer(
      "✅ <b>Payout Request Registered!</b>\nYour request has been placed in"
      " review. You can track its progress in your Wallet.",
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
  amt = amt_row[0] if amt_row else 0.0

  cur.execute("UPDATE withdrawals SET status='paid' WHERE id=?", (w_id,))
  conn.commit()
  conn.close()

  try:
    await bot.send_message(
        chat_id=uid,
        text=(
            f"✅ <b>Payment Completed!</b>\nYour payout of <b>₹{amt:.2f}</b> has"
            " been transferred to your specified UPI ID."
        ),
        parse_mode="HTML",
    )
  except:
    pass

  await call.message.edit_text(
      f"{call.message.text}\n\n✅ <b>STATUS: SETTLED & PAID</b>",
      parse_mode="HTML",
  )
  await call.answer("Payout completed!")


# ======================= ACCOUNT SUBMISSION FLOW =======================
@dp.message(F.text == "⚡ Submit Gmail Tasks")
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
                  text=f"📁 Submit Readymade Account (₹{rate_ready:.2f})",
                  callback_data="mode_readymade",
              )
          ],
      ]
  )
  text = (
      "⚡ <b>Select Account Submission Mode:</b>\n\n"
      f"1️⃣ <b>Create From Bot Data:</b> Payout: <b>₹{rate_bot:.2f}</b> per"
      " account.\n"
      "• You must register using given First/Last Name, DOB, and credentials.\n\n"
      f"2️⃣ <b>Readymade Account:</b> Payout: <b>₹{rate_ready:.2f}</b> per"
      " account.\n"
      "• Submit your own created Gmail accounts directly.\n\n"
      "Choose which method you are submitting:"
  )
  await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "mode_readymade")
async def start_readymade_flow(call: types.CallbackQuery, state: FSMContext):
  rate_ready = get_rate("readymade")
  await state.update_data(acc_type="Readymade")

  msg = (
      "📁 <b>Readymade Account Submission</b>\n"
      "━━━━━━━━━━━━━━━━━━━━━━\n"
      f"💰 <b>Reward:</b> ₹{rate_ready:.2f} per approved Gmail\n\n"
      "⚠️ <b>Important Guidelines:</b>\n"
      "• Account must be active and accessible.\n"
      "• Do not submit suspended, disabled, or locked accounts.\n"
      "• Always check credentials twice before submitting.\n\n"
      "📧 <b>Please send your Gmail Address:</b>\n"
      "<i>(Example: john.doe982@gmail.com)</i>"
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
        "⚠️ <b>Task Data Out of Stock!</b>\n\nAll current task allocations are"
        " exhausted. Please wait while our team uploads a fresh batch.",
        parse_mode="HTML",
    )
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🚨 <b>STOCK EMPTY ALERT:</b>\nA user requested task data, but"
            " available stock is <b>0</b>!\nUse /admin to upload accounts."
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
      f"First name: {fn}\n"
      f"Last name: {ln}\n"
      "----------\n"
      "Date of birth\n"
      f"Month: {month} | Day: {day} | Year: {year}\n"
      "----------\n"
      f"Email: {email}\n"
      "----------\n"
      f"Password: {password}\n"
      "----------\n"
      "🔒 <b>Notice:</b> Be sure to use the exact specified data, otherwise the"
      " account will not be approved or paid.\n\n"
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
        "⚠️ <b>Invalid Email:</b> Please provide a standard address ending with"
        " @gmail.com",
        parse_mode="HTML",
    )
    return
  await state.update_data(email=email)
  await message.answer(
      "🔑 Enter the <b>Password</b> of this account:", parse_mode="HTML"
  )
  await state.set_state(SubmitState.waiting_for_password)


@dp.message(SubmitState.waiting_for_password)
async def process_sub_password(message: types.Message, state: FSMContext):
  await state.update_data(password=message.text.strip())

  skip_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="⏭ Skip Recovery Email", callback_data="skip_rec"
          )
      ]]
  )
  await message.answer(
      "🛡 <b>Recovery Email Check:</b>\nSend the recovery email if attached, or"
      " tap <b>Skip</b>.",
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
                  text="🔐 Provide 2FA Key (Faster Approval)",
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
      "🔐 <b>Two-Factor Authentication (2FA):</b>\nAttaching 2FA keys improves"
      " validation speed.\nChoose an option:",
      parse_mode="HTML",
      reply_markup=kb,
  )
  await state.set_state(SubmitState.waiting_for_2fa_choice)


@dp.callback_query(F.data == "2fa_no", SubmitState.waiting_for_2fa_choice)
async def sub_no_2fa(call: types.CallbackQuery, state: FSMContext):
  await state.update_data(two_fa="None")
  await finalize_submission(call.message, call.from_user, state)
  await call.answer()


@dp.callback_query(F.data == "2fa_yes", SubmitState.waiting_for_2fa_choice)
async def sub_yes_2fa(call: types.CallbackQuery, state: FSMContext):
  await call.message.answer(
      "🔑 Paste your <b>2FA Secret Key / Backup Code</b> below:",
      parse_mode="HTML",
  )
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

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      """
        INSERT INTO submissions (user_id, acc_type, email, password, recovery, two_fa, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
    """,
      (user.id, acc_type, email, pwd, rec, two_fa),
  )
  sub_id = cur.lastrowid

  cur.execute(
      "UPDATE users SET total_submitted = total_submitted + 1 WHERE user_id=?",
      (user.id,),
  )
  conn.commit()
  conn.close()

  rate_preview = (
      get_rate("botdata") if "Bot" in acc_type else get_rate("readymade")
  )

  admin_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text=f"✅ Approve (+₹{rate_preview:.2f})",
              callback_data=f"adm_app_{sub_id}",
          ),
          InlineKeyboardButton(
              text="❌ Reject", callback_data=f"adm_rej_{sub_id}"
          ),
      ]]
  )

  await bot.send_message(
      chat_id=ADMIN_ID,
      text=(
          f"📥 <b>New Submission #{sub_id}</b>\n"
          f"👤 User: @{user.username} (ID: <code>{user.id}</code>)\n"
          f"🏷 Type: <b>{acc_type}</b> (Rate: ₹{rate_preview:.2f})\n\n"
          f"📧 Email: <code>{email}</code>\n"
          f"🔑 Password: <code>{pwd}</code>\n"
          f"🛡 Recovery: <code>{rec}</code>\n"
          f"🔐 2FA: <code>{two_fa}</code>"
      ),
      parse_mode="HTML",
      reply_markup=admin_kb,
  )

  await msg_obj.answer(
      "✅ <b>Account Submitted Successfully!</b>\n\n"
      "Status: ⏳ <b>Pending Verification</b>\n"
      "Review Period: 24 to 72 Hours\n\n"
      "You can track this submission live under <b>📊 My Submissions</b>.",
      parse_mode="HTML",
  )
  await state.clear()


# ======================= ADMIN VERIFICATION ACTIONS =======================
@dp.callback_query(F.data.startswith("adm_app_"))
async def admin_approve_submission(call: types.CallbackQuery):
  sub_id = int(call.data.split("_")[2])

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT user_id, email, status, acc_type FROM submissions WHERE id=?",
      (sub_id,),
  )
  row = cur.fetchone()

  if not row or str(row[2]).lower() != "pending":
    conn.close()
    await call.answer("This task has already been processed.", show_alert=True)
    return

  uid, mail, _, acc_type = row
  reward = get_rate("botdata") if "Bot" in str(acc_type) else get_rate("readymade")

  # Guaranteed disk balance update
  cur.execute(
      "UPDATE submissions SET status='approved' WHERE id=?", (sub_id,)
  )
  cur.execute(
      "UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, uid)
  )
  conn.commit()

  # Fetch new balance
  cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
  new_bal = cur.fetchone()[0]
  conn.close()

  try:
    await bot.send_message(
        chat_id=int(uid),
        text=(
            f"🎉 <b>Account Approved!</b>\nYour account <code>{mail}</code>"
            f" passed verification.\n<b>+₹{reward:.2f}</b> has been credited"
            f" to your wallet!\n💵 Current Balance: <b>₹{new_bal:.2f}</b>"
        ),
        parse_mode="HTML",
    )
  except Exception as e:
    print(f"Error sending approve msg to {uid}: {e}")

  await call.message.edit_text(
      f"{call.message.text}\n\n✅ <b>STATUS: APPROVED (+₹{reward:.2f})</b>",
      parse_mode="HTML",
  )
  await call.answer("Approved!")


# --- REJECT MENU WITH INSTANT REASON BUTTONS ---
@dp.callback_query(F.data.startswith("adm_rej_"))
async def admin_reject_menu(call: types.CallbackQuery):
  sub_id = int(call.data.split("_")[2])

  conn = get_db()
  cur = conn.cursor()
  cur.execute("SELECT status FROM submissions WHERE id=?", (sub_id,))
  row = cur.fetchone()
  conn.close()

  if not row or str(row[0]).lower() != "pending":
    await call.answer("This task has already been processed.", show_alert=True)
    return

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="❌ Wrong Password",
                  callback_data=f"rk_{sub_id}_Wrong Password",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔒 2FA / OTP Locked",
                  callback_data=f"rk_{sub_id}_2FA Locked",
              )
          ],
          [
              InlineKeyboardButton(
                  text="⚠️ Account Disabled",
                  callback_data=f"rk_{sub_id}_Account Disabled",
              )
          ],
          [
              InlineKeyboardButton(
                  text="✏️ Custom Reason (Type)",
                  callback_data=f"rcust_{sub_id}",
              )
          ],
      ]
  )

  await call.message.reply(
      f"❌ <b>Select Rejection Reason for #{sub_id}:</b>",
      parse_mode="HTML",
      reply_markup=kb,
  )
  await call.answer()


@dp.callback_query(F.data.startswith("rk_"))
async def admin_reject_quick(call: types.CallbackQuery):
  parts = call.data.split("_", 2)
  sub_id = int(parts[1])
  reason = parts[2]

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT user_id, email, status FROM submissions WHERE id=?", (sub_id,)
  )
  row = cur.fetchone()

  if not row or str(row[2]).lower() != "pending":
    conn.close()
    await call.answer("This task has already been processed.", show_alert=True)
    return

  uid, mail, _ = row
  cur.execute(
      "UPDATE submissions SET status='rejected', rejection_reason=? WHERE"
      " id=?",
      (reason, sub_id),
  )
  conn.commit()
  conn.close()

  try:
    user_alert = (
        f"❌ <b>Submission Rejected</b>\n\n"
        f"Account: <code>{mail}</code>\n"
        f"<b>Reason:</b> {reason}\n\n"
        "You can check your status log inside 📊 My Submissions."
    )
    await bot.send_message(chat_id=int(uid), text=user_alert, parse_mode="HTML")
  except Exception as e:
    print(f"Error sending reject alert to user {uid}: {e}")

  await call.message.edit_text(
      f"❌ <b>Submission #{sub_id} Rejected</b>\nReason: <b>{reason}</b>",
      parse_mode="HTML",
  )
  await call.answer("Rejected!")


@dp.callback_query(F.data.startswith("rcust_"))
async def admin_reject_custom_start(
    call: types.CallbackQuery, state: FSMContext
):
  sub_id = int(call.data.split("_")[1])
  await state.update_data(target_sub_id=sub_id)
  await call.message.answer(
      f"✏️ <b>Type custom rejection reason for #{sub_id} below:</b>",
      parse_mode="HTML",
  )
  await state.set_state(AdminState.waiting_for_custom_reject)
  await call.answer()


@dp.message(AdminState.waiting_for_custom_reject)
async def admin_reject_custom_save(
    message: types.Message, state: FSMContext
):
  if message.from_user.id != ADMIN_ID:
    return
  data = await state.get_data()
  sub_id = data.get("target_sub_id")
  reason = message.text.strip()

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "SELECT user_id, email FROM submissions WHERE id=?", (sub_id,)
  )
  row = cur.fetchone()

  if row:
    uid, mail = row
    cur.execute(
        "UPDATE submissions SET status='rejected', rejection_reason=? WHERE"
        " id=?",
        (reason, sub_id),
    )
    conn.commit()

    try:
      user_alert = (
          f"❌ <b>Submission Rejected</b>\n\n"
          f"Account: <code>{mail}</code>\n"
          f"<b>Reason:</b> {reason}\n\n"
          "You can check your status log inside 📊 My Submissions."
      )
      await bot.send_message(
          chat_id=int(uid), text=user_alert, parse_mode="HTML"
      )
    except Exception as e:
      print(f"Error sending reject alert to user {uid}: {e}")

  conn.close()
  await message.answer(
      f"✅ Submission #{sub_id} rejected with reason: <b>{reason}</b>",
      parse_mode="HTML",
  )
  await state.clear()


# ======================= ADMIN CONTROL DASHBOARD =======================
@dp.message(Command("admin"))
async def admin_control_panel(message: types.Message):
  if message.from_user.id != ADMIN_ID:
    return

  conn = get_db()
  cur = conn.cursor()
  cur.execute("SELECT COUNT(*) FROM users")
  total_users = cur.fetchone()[0]

  cur.execute(
      "SELECT COUNT(*) FROM submissions WHERE LOWER(status)='pending'"
  )
  pending_subs = cur.fetchone()[0]
  conn.close()

  available_stock = get_available_stock_count()
  r_ready = get_rate("readymade")
  r_bot = get_rate("botdata")

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📥 Upload Structured Stock",
                  callback_data="adm_upload_stock",
              )
          ],
          [
              InlineKeyboardButton(
                  text=f"⚙️ Readymade Rate (₹{r_ready:.2f})",
                  callback_data="rate_change_readymade",
              ),
              InlineKeyboardButton(
                  text=f"⚙️ Bot Data Rate (₹{r_bot:.2f})",
                  callback_data="rate_change_botdata",
              ),
          ],
          [
              InlineKeyboardButton(
                  text="💳 Add / Deduct Balance", callback_data="adm_add_bal"
              )
          ],
      ]
  )

  dashboard = (
      "👑 <b>Admin Master Panel</b>\n"
      "━━━━━━━━━━━━━━━━━━━━━━\n"
      f"👥 <b>Total Users:</b> {total_users}\n"
      f"📦 <b>Task Stock Ready:</b> {available_stock}\n"
      f"⏳ <b>Pending Submissions:</b> {pending_subs}\n\n"
      "💰 <b>Rates:</b>\n"
      f"• 📁 Readymade: ₹{r_ready:.2f}\n"
      f"• 📋 Bot-Data: ₹{r_bot:.2f}"
  )
  await message.answer(dashboard, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "adm_upload_stock")
async def adm_upload_stock_prompt(
    call: types.CallbackQuery, state: FSMContext
):
  if call.from_user.id != ADMIN_ID:
    return
  msg = (
      "📥 <b>Upload Structured Task Data:</b>\n\n"
      "Send entries using the format below (one per line):\n"
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
  conn = get_db()
  cur = conn.cursor()

  for line in lines:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) == 7:
      fn, ln, month, day, year, mail, pwd = parts
      try:
        cur.execute(
            """
                    INSERT INTO task_stock (first_name, last_name, dob_month, dob_day, dob_year, email, password)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
            (fn, ln, month, day, year, mail, pwd),
        )
        added += 1
      except sqlite3.IntegrityError:
        pass

  conn.commit()
  conn.close()

  await message.answer(
      f"✅ <b>Stock Uploaded:</b> Added <b>{added}</b> profiles.\n"
      f"Total available stock: <b>{get_available_stock_count()}</b>",
      parse_mode="HTML",
  )
  await state.clear()


@dp.callback_query(F.data.startswith("rate_change_"))
async def adm_rate_change_prompt(call: types.CallbackQuery, state: FSMContext):
  if call.from_user.id != ADMIN_ID:
    return
  rate_type = call.data.split("_")[2]  # readymade or botdata
  label = "Readymade Accounts" if rate_type == "readymade" else "Bot-Data Tasks"
  await state.update_data(target_rate_type=rate_type)
  await call.message.answer(
      f"⚙️ Enter new rate for <b>{label}</b> (e.g. 15 or 18.5):",
      parse_mode="HTML",
  )
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
    set_rate(rate_type, val)
    label = (
        "Readymade Accounts" if rate_type == "readymade" else "Bot-Data Tasks"
    )
    await message.answer(
        f"✅ Rate for <b>{label}</b> updated to: <b>₹{val:.2f}</b>",
        parse_mode="HTML",
    )
  except ValueError:
    await message.answer("⚠️ Please enter a valid number.")
  await state.clear()


@dp.callback_query(F.data == "adm_add_bal")
async def adm_add_balance_prompt(
    call: types.CallbackQuery, state: FSMContext
):
  if call.from_user.id != ADMIN_ID:
    return
  await call.message.answer("Enter target Telegram User ID:")
  await state.set_state(AdminState.waiting_for_addbal_id)
  await call.answer()


@dp.message(AdminState.waiting_for_addbal_id)
async def adm_process_addbal_uid(message: types.Message, state: FSMContext):
  await state.update_data(target_uid=message.text.strip())
  await message.answer(
      "Enter amount to add or deduct (e.g. <code>50</code> or"
      " <code>-15</code>):",
      parse_mode="HTML",
  )
  await state.set_state(AdminState.waiting_for_addbal_amount)


@dp.message(AdminState.waiting_for_addbal_amount)
async def adm_process_addbal_amt(message: types.Message, state: FSMContext):
  data = await state.get_data()
  uid = int(data["target_uid"])
  amt = float(message.text.strip())

  conn = get_db()
  cur = conn.cursor()
  cur.execute(
      "UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, uid)
  )
  conn.commit()
  conn.close()

  await message.answer(
      f"✅ Balance adjusted for user <code>{uid}</code> by ₹{amt:.2f}.",
      parse_mode="HTML",
  )
  await state.clear()


# ======================= MAIN ENTRY =======================
async def main():
  flask_thread = threading.Thread(target=run_flask, daemon=True)
  flask_thread.start()

  print("=" * 45)
  print("🔥 GMAIL SELLER BOT ACTIVE ON RENDER 🔥")
  print("=" * 45)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
