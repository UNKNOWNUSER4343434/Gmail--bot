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


# ======================= KEYBOARDS =======================
def get_main_menu():
  return ReplyKeyboardMarkup(
      keyboard=[
          [KeyboardButton(text="🚀 Sell Account")],
          [
              KeyboardButton(text="💼 Wallet & Balance"),
              KeyboardButton(text="💸 Request Payout"),
          ],
          [
              KeyboardButton(text="📢 Updates Channel"),
              KeyboardButton(text="🛠 24/7 Support"),
          ],
      ],
      resize_keyboard=True,
  )


# ======================= BASIC COMMANDS =======================
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
      f"👋 **Welcome, {message.from_user.first_name}!**\n\n"
      f"⚡ **Earning Rate:** ₹{rate:.2f} per verified Gmail\n"
      f"⏱ **Review Duration:** Within 24 - 72 Hours (3 Days Max)\n\n"
      f"Select an option from the menu below to get started."
  )
  await message.answer(
      welcome_text, parse_mode="Markdown", reply_markup=get_main_menu()
  )


@dp.message(F.text == "📢 Updates Channel")
async def updates_handler(message: types.Message):
  await message.answer(
      f"📢 **Official Announcement Channel:**\nJoin here: {CHANNEL_LINK}",
      disable_web_page_preview=True,
  )


@dp.message(F.text == "🛠 24/7 Support")
async def support_handler(message: types.Message):
  await message.answer(
      f"🛠 **Customer Support:**\nFor any inquiries or issues, contact:"
      f" {SUPPORT_USER}"
  )


@dp.message(F.text == "💼 Wallet & Balance")
async def wallet_handler(message: types.Message):
  cursor.execute(
      "SELECT balance, total_submitted FROM users WHERE user_id=?",
      (message.from_user.id,),
  )
  row = cursor.fetchone()
  bal = row[0] if row else 0.0
  subs = row[1] if row else 0

  text = (
      f"💼 **Your Wallet Dashboard**\n\n"
      f"💵 **Available Balance:** ₹{bal:.2f}\n"
      f"📦 **Accounts Submitted:** {subs}\n"
      f"💳 **Minimum Payout:** ₹{get_rate():.2f}"
  )
  await message.answer(text, parse_mode="Markdown")


# ======================= ACCOUNT SELLING FLOW =======================
@dp.message(F.text == "🚀 Sell Account")
async def choose_method(message: types.Message):
  markup = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📁 Sell Readymade Account", callback_data="sell_ready"
              )
          ],
          [
              InlineKeyboardButton(
                  text="📋 Create From Bot Data", callback_data="sell_botdata"
              )
          ],
      ]
  )
  await message.answer(
      "Please select how you would like to submit the account:",
      reply_markup=markup,
  )


@dp.callback_query(F.data == "sell_ready")
async def start_readymade(call: types.CallbackQuery, state: FSMContext):
  await state.update_data(acc_type="Readymade")
  await call.message.answer(
      "📧 **Enter your Gmail Address:**\n*(Example: john.doe982@gmail.com)*",
      parse_mode="Markdown",
  )
  await state.set_state(SubmitState.waiting_for_email)
  await call.answer()


@dp.callback_query(F.data == "sell_botdata")
async def start_botdata(call: types.CallbackQuery, state: FSMContext):
  user_id = call.from_user.id

  cursor.execute(
      "SELECT id, email, password FROM task_stock WHERE status='available'"
      " LIMIT 1"
  )
  item = cursor.fetchone()

  if not item:
    await call.message.answer(
        "⚠️ **Task Data Out of Stock!**\n\n"
        "Currently, there is no task data available. Please wait a short"
        " while. Our team will add fresh tasks shortly."
    )
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🚨 **STOCK ALERT:**\nA user tried to request task data, but the"
            " stock is **EMPTY (0)**!\nUse `/admin` -> **Upload Task Data** to"
            " restock."
        ),
        parse_mode="Markdown",
    )
    await call.answer()
    return

  stock_id, assigned_email, assigned_password = item

  cursor.execute(
      "UPDATE task_stock SET status='assigned', assigned_to=? WHERE id=?",
      (user_id, stock_id),
  )
  conn.commit()

  remaining = get_available_stock_count()
  if remaining == 0:
    await bot.send_message(
        chat_id=ADMIN_ID,
        text="⚠️ **Stock Warning:** The last task data was just assigned! Available stock is now 0.",
    )

  await state.update_data(acc_type="Bot-Data Task")

  msg = (
      "📋 **Assigned Task Credentials:**\n\n"
      f"📩 **Assigned Email:** `{assigned_email}`\n"
      f"🔑 **Assigned Password:** `{assigned_password}`\n\n"
      "📌 *Instructions:*\n"
      "1. Create a new Google Account using the **exact email and password**"
      " provided above.\n"
      "2. Once registered, type and send that **Email Address** here:"
  )
  await call.message.answer(msg, parse_mode="Markdown")
  await state.set_state(SubmitState.waiting_for_email)
  await call.answer()


@dp.message(SubmitState.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
  email = message.text.strip()
  if "@gmail.com" not in email.lower():
    await message.answer(
        "⚠️ **Invalid Format:** Please enter a valid Gmail address ending with"
        " `@gmail.com`:"
    )
    return
  await state.update_data(email=email)
  await message.answer("🔑 Enter the **Password** of this account:")
  await state.set_state(SubmitState.waiting_for_password)


@dp.message(SubmitState.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
  await state.update_data(password=message.text.strip())

  skip_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="⏭ Skip Recovery Email", callback_data="skip_recovery"
          )
      ]]
  )
  await message.answer(
      "🛡 **Recovery Email Check:**\n"
      "Did you attach a recovery email? If yes, send it now. Otherwise, tap"
      " **Skip**.",
      reply_markup=skip_kb,
  )
  await state.set_state(SubmitState.waiting_for_recovery)


@dp.message(SubmitState.waiting_for_recovery)
async def process_recovery_text(message: types.Message, state: FSMContext):
  await state.update_data(recovery=message.text.strip())
  await ask_2fa_step(message, state)


@dp.callback_query(F.data == "skip_recovery", SubmitState.waiting_for_recovery)
async def skip_recovery(call: types.CallbackQuery, state: FSMContext):
  await state.update_data(recovery="None")
  await ask_2fa_step(call.message, state)
  await call.answer()


async def ask_2fa_step(message_obj, state: FSMContext):
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🔐 Yes, Provide 2FA Key (High Approval)",
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
  info_text = (
      "🔐 **Two-Factor Authentication (2FA):**\n\n"
      "💡 *Tip:* Adding 2FA backup/secret keys drastically increases"
      " verification speed and prevents lockouts.\n\n"
      "Do you want to provide a 2FA Key, or submit without it?"
  )
  await message_obj.answer(info_text, parse_mode="Markdown", reply_markup=kb)
  await state.set_state(SubmitState.waiting_for_2fa_choice)


@dp.callback_query(F.data == "2fa_no", SubmitState.waiting_for_2fa_choice)
async def submit_without_2fa(call: types.CallbackQuery, state: FSMContext):
  await state.update_data(two_fa="None")
  await final_submission(call.message, call.from_user, state)
  await call.answer()


@dp.callback_query(F.data == "2fa_yes", SubmitState.waiting_for_2fa_choice)
async def ask_2fa_key(call: types.CallbackQuery, state: FSMContext):
  await call.message.answer(
      "🔑 Please paste your **2FA Secret Key / Backup Code** below:"
  )
  await state.set_state(SubmitState.waiting_for_2fa_key)
  await call.answer()


@dp.message(SubmitState.waiting_for_2fa_key)
async def process_2fa_key(message: types.Message, state: FSMContext):
  await state.update_data(two_fa=message.text.strip())
  await final_submission(message, message.from_user, state)


async def final_submission(message_obj, user, state: FSMContext):
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
          f"📥 **New Submission #{sub_id}**\n"
          f"👤 User: @{user.username} (ID: `{user.id}`)\n"
          f"🏷 Source: **{acc_type}**\n\n"
          f"📧 **Email:** `{email}`\n"
          f"🔑 **Password:** `{pwd}`\n"
          f"🛡 **Recovery:** `{rec}`\n"
          f"🔐 **2FA Key:** `{two_fa}`"
      ),
      parse_mode="Markdown",
      reply_markup=admin_kb,
  )

  await message_obj.answer(
      "✅ **Account Submitted Successfully!**\n\n"
      "⏳ **Status:** Pending Review\n"
      "🕒 Your details will be verified by our team within **24 to 72 hours**"
      " (up to 3 days).\n"
      "Once approved, your balance will automatically be credited to your"
      " wallet.",
      parse_mode="Markdown",
  )
  await state.clear()


# ======================= ADMIN ACTIONS (APPROVE/REJECT) =======================
@dp.callback_query(F.data.startswith("adm_app_"))
async def admin_approve(call: types.CallbackQuery):
  sub_id = int(call.data.split("_")[2])
  cursor.execute(
      "SELECT user_id, email, status FROM submissions WHERE id=?", (sub_id,)
  )
  row = cursor.fetchone()

  if not row or row[2] != "pending":
    await call.answer("This submission has already been processed.", show_alert=True)
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
            f"🎉 **Congratulations!**\nYour account `{mail}` has been"
            f" **Approved**.\n**₹{rate:.2f}** has been credited to your"
            " wallet!"
        ),
        parse_mode="Markdown",
    )
  except:
    pass

  await call.message.edit_text(
      f"{call.message.text}\n\n✅ **STATUS: APPROVED (+₹{rate:.2f})**",
      parse_mode="Markdown",
  )
  await call.answer("Approved!")


@dp.callback_query(F.data.startswith("adm_rej_"))
async def admin_reject(call: types.CallbackQuery):
  sub_id = int(call.data.split("_")[2])
  cursor.execute(
      "SELECT user_id, email, status FROM submissions WHERE id=?", (sub_id,)
  )
  row = cursor.fetchone()

  if not row or row[2] != "pending":
    await call.answer("This submission has already been processed.", show_alert=True)
    return

  uid, mail, _ = row
  cursor.execute(
      "UPDATE submissions SET status='rejected' WHERE id=?", (sub_id,)
  )
  conn.commit()

  try:
    await bot.send_message(
        chat_id=uid,
        text=(
            f"❌ **Submission Rejected:**\nYour account `{mail}` could not be"
            " approved due to invalid credentials, incorrect password, or"
            " activation lock."
        ),
        parse_mode="Markdown",
    )
  except:
    pass

  await call.message.edit_text(
      f"{call.message.text}\n\n❌ **STATUS: REJECTED**", parse_mode="Markdown"
  )
  await call.answer("Rejected!")


# ======================= PAYOUT FLOW =======================
@dp.message(F.text == "💸 Request Payout")
async def withdraw_menu(message: types.Message, state: FSMContext):
  cursor.execute(
      "SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)
  )
  row = cursor.fetchone()
  bal = row[0] if row else 0.0
  rate = get_rate()

  if bal < rate:
    await message.answer(
        f"⚠️ **Insufficient Funds:**\nMinimum payout is **₹{rate:.2f}**.\nYour"
        f" balance: **₹{bal:.2f}**",
        parse_mode="Markdown",
    )
    return

  await message.answer(
      "📱 Please enter your **UPI ID** where you wish to receive payment:\n*(e.g."
      " `9876543210@paytm`)*",
      parse_mode="Markdown",
  )
  await state.set_state(WithdrawState.waiting_for_upi)


@dp.message(WithdrawState.waiting_for_upi)
async def process_withdraw(message: types.Message, state: FSMContext):
  upi = message.text.strip()
  uid = message.from_user.id

  cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
  bal = cursor.fetchone()[0]

  cursor.execute("UPDATE users SET balance=0.0 WHERE user_id=?", (uid,))
  conn.commit()

  pay_kb = InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="💸 Mark as Paid", callback_data=f"paid_{uid}_{bal}"
          )
      ]]
  )

  await bot.send_message(
      chat_id=ADMIN_ID,
      text=(
          f"🔔 **New Payout Request**\n\n"
          f"👤 User: @{message.from_user.username} (ID: `{uid}`)\n"
          f"💵 Amount: **₹{bal:.2f}**\n"
          f"📱 UPI Address: `{upi}`"
      ),
      parse_mode="Markdown",
      reply_markup=pay_kb,
  )

  await message.answer(
      "✅ **Payout Request Received!**\nYour payment will be processed"
      " shortly."
  )
  await state.clear()


@dp.callback_query(F.data.startswith("paid_"))
async def mark_paid(call: types.CallbackQuery):
  _, uid, amt = call.data.split("_")
  try:
    await bot.send_message(
        chat_id=int(uid),
        text=(
            f"✅ **Payment Completed!**\nYour payout of **₹{amt}** has been sent"
            " to your UPI ID."
        ),
        parse_mode="Markdown",
    )
  except:
    pass
  await call.message.edit_text(
      f"{call.message.text}\n\n✅ **STATUS: PAID & SETTLED**",
      parse_mode="Markdown",
  )
  await call.answer("Payout completed!")


# ======================= ADMIN CONTROL DASHBOARD =======================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
  if message.from_user.id != ADMIN_ID:
    return

  cursor.execute("SELECT COUNT(*) FROM users")
  total_users = cursor.fetchone()[0]

  cursor.execute("SELECT COUNT(*) FROM submissions WHERE status='pending'")
  pending_subs = cursor.fetchone()[0]

  available_stock = get_available_stock_count()

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📥 Upload Task Data (Stock)",
                  callback_data="adm_upload_stock",
              )
          ],
          [
              InlineKeyboardButton(
                  text="⚙️ Update Rate Per Mail",
                  callback_data="adm_change_rate",
              )
          ],
          [
              InlineKeyboardButton(
                  text="💳 Add/Deduct Balance", callback_data="adm_add_bal"
              )
          ],
      ]
  )

  await message.answer(
      f"👑 **Admin Control Panel**\n\n"
      f"👥 **Total Users:** {total_users}\n"
      f"📦 **Available Task Stock:** {available_stock}\n"
      f"⏳ **Pending Submissions:** {pending_subs}\n"
      f"💰 **Current Rate:** ₹{get_rate():.2f}",
      parse_mode="Markdown",
      reply_markup=kb,
  )


# --- Stock Upload ---
@dp.callback_query(F.data == "adm_upload_stock")
async def adm_upload_stock_start(call: types.CallbackQuery, state: FSMContext):
  if call.from_user.id != ADMIN_ID:
    return
  msg = (
      "📥 **Upload Bulk Task Data:**\n\n"
      "Send accounts in this format (one per line):\n"
      "`email@gmail.com:password`\n"
      "`another@gmail.com:password123`\n\n"
      "Paste your list below:"
  )
  await call.message.answer(msg, parse_mode="Markdown")
  await state.set_state(AdminState.waiting_for_bulk_stock)
  await call.answer()


@dp.message(AdminState.waiting_for_bulk_stock)
async def process_bulk_stock(message: types.Message, state: FSMContext):
  if message.from_user.id != ADMIN_ID:
    return
  lines = message.text.strip().split("\n")
  added = 0
  for line in lines:
    if ":" in line:
      parts = line.split(":", 1)
      mail = parts[0].strip()
      pwd = parts[1].strip()
      try:
        cursor.execute(
            "INSERT INTO task_stock (email, password) VALUES (?, ?)",
            (mail, pwd),
        )
        added += 1
      except sqlite3.IntegrityError:
        pass
  conn.commit()

  await message.answer(
      f"✅ **Import Successful!**\nAdded **{added}** accounts to task stock.\n"
      f"Total Available Stock: **{get_available_stock_count()}**"
  )
  await state.clear()


# --- Update Rate ---
@dp.callback_query(F.data == "adm_change_rate")
async def adm_rate_change(call: types.CallbackQuery, state: FSMContext):
  if call.from_user.id != ADMIN_ID:
    return
  await call.message.answer("Enter new payout rate per Gmail (e.g., 15 or 20):")
  await state.set_state(AdminState.waiting_for_new_rate)
  await call.answer()


@dp.message(AdminState.waiting_for_new_rate)
async def process_new_rate(message: types.Message, state: FSMContext):
  if message.from_user.id != ADMIN_ID:
    return
  try:
    new_val = float(message.text.strip())
    set_rate(new_val)
    await message.answer(
        f"✅ Rate successfully updated to: **₹{new_val:.2f}** per account.",
        parse_mode="Markdown",
    )
  except ValueError:
    await message.answer("⚠️ Please enter a valid numeric value.")
  await state.clear()


# --- Add Balance Manually ---
@dp.callback_query(F.data == "adm_add_bal")
async def adm_add_balance(call: types.CallbackQuery, state: FSMContext):
  if call.from_user.id != ADMIN_ID:
    return
  await call.message.answer("Enter the numeric **Telegram User ID**:")
  await state.set_state(AdminState.waiting_for_addbal_id)
  await call.answer()


@dp.message(AdminState.waiting_for_addbal_id)
async def process_bal_uid(message: types.Message, state: FSMContext):
  await state.update_data(target_uid=message.text.strip())
  await message.answer(
      "Enter amount to add/deduct (e.g., `50` to add, `-15` to deduct):"
  )
  await state.set_state(AdminState.waiting_for_addbal_amount)


@dp.message(AdminState.waiting_for_addbal_amount)
async def process_bal_amt(message: types.Message, state: FSMContext):
  data = await state.get_data()
  uid = int(data["target_uid"])
  amt = float(message.text.strip())

  cursor.execute(
      "UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, uid)
  )
  conn.commit()

  await message.answer(
      f"✅ Updated balance for User ID `{uid}` by ₹{amt:.2f}.",
      parse_mode="Markdown",
  )
  await state.clear()


# ======================= MAIN ENTRY =======================
async def main():
  flask_thread = threading.Thread(target=run_flask, daemon=True)
  flask_thread.start()

  print("=" * 45)
  print("🔥 GMAIL SELLER BOT IS RUNNING ON RENDER 🔥")
  print("=" * 45)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
