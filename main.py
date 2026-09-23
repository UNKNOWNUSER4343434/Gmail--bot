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
conn = sqlite3.connect("gmail_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance REAL DEFAULT 0.0,
    total_submitted INTEGER DEFAULT 0
)
""")

cursor.execute("""
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

cursor.execute("""
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    upi_id TEXT,
    status TEXT DEFAULT 'pending'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
cursor.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES ('rate', '15.0')"
)
conn.commit()


def get_rate():
  cursor.execute("SELECT value FROM settings WHERE key='rate'")
  return float(cursor.fetchone()[0])


def set_rate(new_rate):
  cursor.execute(
      "UPDATE settings SET value=? WHERE key='rate'", (str(new_rate),)
  )
  conn.commit()


def get_available_stock_count():
  cursor.execute(
      "SELECT COUNT(*) FROM task_stock WHERE status='available'"
  )
  return cursor.fetchone()[0]


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
  waiting_for_new_rate = State()
  waiting_for_addbal_id = State()
  waiting_for_addbal_amount = State()
  waiting_for_reject_reason = State()


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

  cursor.execute(
      "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
      (user_id, username),
  )
  conn.commit()

  rate = get_rate()
  welcome_text = (
      f"👋 <b>Welcome, {message.from_user.first_name}!</b>\n\n"
      f"⚡ <b>Earning Rate:</b> ₹{rate:.2f} per verified account\n"
      "⏱ <b>Verification Window:</b> 24 to 72 Hours max\n\n"
      "Use the menu below to navigate and earn directly."
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

  cursor.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=?", (user_id,)
  )
  total = cursor.fetchone()[0]

  cursor.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=? AND LOWER(status) ="
      " 'pending'",
      (user_id,),
  )
  pending = cursor.fetchone()[0]

  cursor.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=? AND LOWER(status) ="
      " 'approved'",
      (user_id,),
  )
  approved = cursor.fetchone()[0]

  cursor.execute(
      "SELECT COUNT(*) FROM submissions WHERE user_id=? AND LOWER(status) ="
      " 'rejected'",
      (user_id,),
  )
  rejected = cursor.fetchone()[0]

  cursor.execute(
      "SELECT email, status, rejection_reason FROM submissions WHERE"
      " user_id=? ORDER BY id DESC LIMIT 10",
      (user_id,),
  )
  recent_subs = cursor.fetchall()

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
    for s_mail, s_status, s_reason in recent_subs:
      st = s_status.lower()
      if st == "approved":
        tag = "✅ Approved"
      elif st == "rejected":
        tag = f"❌ Rejected ({s_reason})" if s_reason else "❌ Rejected"
      else:
        tag = "⏳ Pending"
      text += f"• <code>{s_mail}</code> ➔ {tag}\n"

  await message.answer(text, parse_mode="HTML")


# ======================= WALLET DASHBOARD =======================
@dp.message(F.text == "💼 My Wallet")
async def wallet_dashboard(message: types.Message):
  user_id = message.from_user.id
  cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
  user_row = cursor.fetchone()
  balance = user_row[0] if user_row else 0.0
  min_payout = get_rate()

  cursor.execute(
      "SELECT amount, upi_id, status FROM withdrawals WHERE user_id=? ORDER BY"
      " id DESC LIMIT 3",
      (user_id,),
  )
  withdrawals = cursor.fetchall()

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
          "✅ Paid" if w_status.lower() == "paid" else "⏳ Pending Review"
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
  cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
  row = cursor.fetchone()
  balance = row[0] if row else 0.0
  min_payout = get_rate()

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

  cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
  balance = cursor.fetchone()[0]

  cursor.execute("UPDATE users SET balance=0.0 WHERE user_id=?", (user_id,))
  cursor.execute(
      "INSERT INTO withdrawals (user_id, amount, upi_id, status) VALUES (?,"
      " ?, ?, 'pending')",
      (user_id, balance, upi),
  )
  w_id = cursor.lastrowid
  conn.commit()

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

  cursor.execute("SELECT amount FROM withdrawals WHERE id=?", (w_id,))
  amt_row = cursor.fetchone()
  amt = amt_row[0] if amt_row else 0.0

  cursor.execute(
      "UPDATE withdrawals SET status='paid' WHERE id=?", (w_id,)
  )
  conn.commit()

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
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📋 Create From Bot Data", callback_data="mode_botdata"
              )
          ],
          [
              InlineKeyboardButton(
                  text="📁 Submit Custom / Readymade",
                  callback_data="mode_readymade",
              )
          ],
      ]
  )
  await message.answer(
      "Choose the submission path that fits your task:", reply_markup=kb
  )


@dp.callback_query(F.data == "mode_readymade")
async def start_readymade_flow(call: types.CallbackQuery, state: FSMContext):
  await state.update_data(acc_type="Readymade")
  await call.message.answer(
      "📧 <b>Enter the Gmail Address:</b>\n<i>(e.g."
      " <code>john.doe982@gmail.com</code>)</i>",
      parse_mode="HTML",
  )
  await state.set_state(SubmitState.waiting_for_email)
  await call.answer()


@dp.callback_query(F.data == "mode_botdata")
async def start_botdata_flow(call: types.CallbackQuery, state: FSMContext):
  user_id = call.from_user.id

  cursor.execute(
      "SELECT id, first_name, last_name, dob_month, dob_day, dob_year, email,"
      " password FROM task_stock WHERE status='available' LIMIT 1"
  )
  item = cursor.fetchone()

  if not item:
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

  cursor.execute(
      "UPDATE task_stock SET status='assigned', assigned_to=? WHERE id=?",
      (user_id, stock_id),
  )
  conn.commit()

  await state.update_data(acc_type="Bot-Data Task")

  task_msg = (
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
      "🔒 Be sure to use the specified data, otherwise the account will not be"
      " paid.\n\n"
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

  cursor.execute(
      """
        INSERT INTO submissions (user_id, acc_type, email, password, recovery, two_fa, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
    """,
      (user.id, acc_type, email, pwd, rec, two_fa),
  )
  sub_id = cursor.lastrowid

  cursor.execute(
      "UPDATE users SET total_submitted = total_submitted + 1 WHERE user_id=?",
      (user.id,),
  )
  conn.commit()

  admin_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="✅ Approve", callback_data=f"adm_app_{sub_id}"
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
          f"🏷 Type: <b>{acc_type}</b>\n\n"
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
  cursor.execute(
      "SELECT user_id, email, status FROM submissions WHERE id=?", (sub_id,)
  )
  row = cursor.fetchone()

  if not row or str(row[2]).lower() != "pending":
    await call.answer("This task has already been processed.", show_alert=True)
    return

  uid, mail, _ = row
  rate = get_rate()

  cursor.execute(
      "UPDATE submissions SET status='approved' WHERE id=?", (sub_id,)
  )
  cursor.execute(
      "UPDATE users SET balance = balance + ? WHERE user_id=?", (rate, uid)
  )
  conn.commit()

  try:
    await bot.send_message(
        chat_id=uid,
        text=(
            f"🎉 <b>Account Approved!</b>\nYour account <code>{mail}</code>"
            f" passed verification.\n<b>₹{rate:.2f}</b> has been credited to"
            " your wallet!"
        ),
        parse_mode="HTML",
    )
  except:
    pass

  await call.message.edit_text(
      f"{call.message.text}\n\n✅ <b>STATUS: APPROVED (+₹{rate:.2f})</b>",
      parse_mode="HTML",
  )
  await call.answer("Approved!")


@dp.callback_query(F.data.startswith("adm_rej_"))
async def admin_reject_start(call: types.CallbackQuery, state: FSMContext):
  sub_id = int(call.data.split("_")[2])
  cursor.execute("SELECT status FROM submissions WHERE id=?", (sub_id,))
  row = cursor.fetchone()

  if not row or str(row[0]).lower() != "pending":
    await call.answer("This task has already been processed.", show_alert=True)
    return

  await state.update_data(target_sub_id=sub_id, original_msg_id=call.message.id)
  await call.message.answer(
      f"❌ <b>Enter rejection reason for submission #{sub_id}:</b>\n<i>(e.g."
      " Wrong password / 2FA locked / Account disabled)</i>",
      parse_mode="HTML",
  )
  await state.set_state(AdminState.waiting_for_reject_reason)
  await call.answer()


@dp.message(AdminState.waiting_for_reject_reason)
async def admin_reject_save(message: types.Message, state: FSMContext):
  if message.from_user.id != ADMIN_ID:
    return
  data = await state.get_data()
  sub_id = data.get("target_sub_id")
  if not sub_id:
    return

  reason = message.text.strip()

  cursor.execute(
      "SELECT user_id, email FROM submissions WHERE id=?", (sub_id,)
  )
  row = cursor.fetchone()

  if row:
    uid, mail = row
    cursor.execute(
        "UPDATE submissions SET status='rejected', rejection_reason=? WHERE"
        " id=?",
        (reason, sub_id),
    )
    conn.commit()

    try:
      await bot.send_message(
          chat_id=uid,
          text=(
              f"❌ <b>Submission Rejected</b>\nAccount: <code>{mail}</code>\n"
              f"<b>Reason:</b> {reason}\n\n"
              "You can check your submission logs inside 📊 My Submissions."
          ),
          parse_mode="HTML",
      )
    except:
      pass

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

  cursor.execute("SELECT COUNT(*) FROM users")
  total_users = cursor.fetchone()[0]

  cursor.execute(
      "SELECT COUNT(*) FROM submissions WHERE LOWER(status)='pending'"
  )
  pending_subs = cursor.fetchone()[0]

  available_stock = get_available_stock_count()

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
                  text="⚙️ Update Rate Per Task",
                  callback_data="adm_change_rate",
              )
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
      f"⏳ <b>Pending Submissions:</b> {pending_subs}\n"
      f"💰 <b>Current Rate:</b> ₹{get_rate():.2f}"
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
  for line in lines:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) == 7:
      fn, ln, month, day, year, mail, pwd = parts
      try:
        cursor.execute(
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

  await message.answer(
      f"✅ <b>Stock Uploaded:</b> Added <b>{added}</b> profiles.\n"
      f"Total available stock: <b>{get_available_stock_count()}</b>",
      parse_mode="HTML",
  )
  await state.clear()


@dp.callback_query(F.data == "adm_change_rate")
async def adm_change_rate_prompt(
    call: types.CallbackQuery, state: FSMContext
):
  if call.from_user.id != ADMIN_ID:
    return
  await call.message.answer(
      "Enter new payout rate per Gmail task (e.g. 15 or 20):"
  )
  await state.set_state(AdminState.waiting_for_new_rate)
  await call.answer()


@dp.message(AdminState.waiting_for_new_rate)
async def adm_process_new_rate(message: types.Message, state: FSMContext):
  if message.from_user.id != ADMIN_ID:
    return
  try:
    val = float(message.text.strip())
    set_rate(val)
    await message.answer(
        f"✅ Rate successfully updated to: <b>₹{val:.2f}</b>", parse_mode="HTML"
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

  cursor.execute(
      "UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, uid)
  )
  conn.commit()

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
