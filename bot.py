# -*- coding: utf-8 -*-
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests
import random
import string

# --- Flask Keep Alive ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'am Marco File Host"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")
# --- End Flask Keep Alive ---

# --- Configuration ---
TOKEN = '8882962643:AAGkKTrN8LExyV55REy9LksCa-O37kEnIQw'
OWNER_ID = 1849126202
ADMIN_ID = 1849126202
YOUR_USERNAME = '@noobxvau'
UPDATE_CHANNEL = 'https://t.me/noobxvau'

# Payment Info
PAYMENT_NUMBER = '019XXXXXXXX'  # Replace with your bKash/Nagad number
PAYMENT_REFERENCE = 'Your Reference Name'

# Folder setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

# File upload limits based on subscription
FREE_USER_LIMIT = 1  # Free users can upload 1 file
SUBSCRIBED_USER_LIMIT = 3  # Subscribed users can upload 3 files
PREMIUM_USER_LIMIT = 5  # Premium users can upload 5 files
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

# Subscription prices (in BDT)
SUBSCRIPTION_PRICES = {
    'basic': 50,    # 50 BDT - 3 bots
    'premium': 100,  # 100 BDT - 5 bots
    'monthly': 200   # 200 BDT - Unlimited bots for 30 days
}

# Subscription types and their limits
SUBSCRIPTION_TYPES = {
    'basic': {'limit': 3, 'duration': 30, 'price': 50},
    'premium': {'limit': 5, 'duration': 30, 'price': 100},
    'monthly': {'limit': 999, 'duration': 30, 'price': 200}
}

# Create necessary directories
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

# Initialize bot
bot = telebot.TeleBot(TOKEN)

# --- Data structures ---
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False
subscription_requests = {}  # {request_id: {user_id, type, status, timestamp, payment_proof}}

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Command Button Layouts ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscription", "📞 Contact Owner"]
]

ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Running All Code"],
    ["👑 Admin Panel", "📞 Contact Owner"],
    ["📋 Pending Requests"]
]

# --- Database Setup ---
def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT, sub_type TEXT, bot_limit INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscription_requests
                     (request_id TEXT PRIMARY KEY, user_id INTEGER, sub_type TEXT, 
                      status TEXT, timestamp TEXT, payment_proof TEXT, admin_notes TEXT)''')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        # Load subscriptions with type and limit
        c.execute('SELECT user_id, expiry, sub_type, bot_limit FROM subscriptions')
        for user_id, expiry, sub_type, bot_limit in c.fetchall():
            try:
                user_subscriptions[user_id] = {
                    'expiry': datetime.fromisoformat(expiry),
                    'type': sub_type,
                    'bot_limit': bot_limit
                }
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry date format for user {user_id}: {expiry}. Skipping.")

        # Load user files
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))

        # Load active users
        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        # Load admins
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())

        # Load subscription requests
        c.execute('SELECT request_id, user_id, sub_type, status, timestamp, payment_proof, admin_notes FROM subscription_requests')
        for req_id, user_id, sub_type, status, timestamp, payment_proof, admin_notes in c.fetchall():
            subscription_requests[req_id] = {
                'user_id': user_id,
                'type': sub_type,
                'status': status,
                'timestamp': timestamp,
                'payment_proof': payment_proof,
                'admin_notes': admin_notes or ''
            }

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins.")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

# Initialize DB and Load Data at startup
init_db()
load_data()

# --- Helper Functions ---
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_subscription_info(user_id):
    """Get user's subscription info"""
    if user_id == OWNER_ID:
        return {'type': 'owner', 'limit': OWNER_LIMIT, 'expiry': None}
    if user_id in admin_ids:
        return {'type': 'admin', 'limit': ADMIN_LIMIT, 'expiry': None}
    
    sub_info = user_subscriptions.get(user_id)
    if sub_info and sub_info.get('expiry') and sub_info['expiry'] > datetime.now():
        return {
            'type': sub_info.get('type', 'basic'),
            'limit': sub_info.get('bot_limit', SUBSCRIBED_USER_LIMIT),
            'expiry': sub_info['expiry']
        }
    return {'type': 'free', 'limit': FREE_USER_LIMIT, 'expiry': None}

def get_user_file_limit(user_id):
    """Get the file upload limit for a user based on subscription"""
    sub_info = get_user_subscription_info(user_id)
    return sub_info['limit']

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def get_user_active_script_count(user_id):
    """Get the number of running scripts for a specific user"""
    count = 0
    for script_key, script_info in list(bot_scripts.items()):
        try:
            owner_id = int(script_key.split('_')[0])
            if owner_id == user_id:
                if is_bot_running(user_id, script_info.get('file_name', '')):
                    count += 1
        except (ValueError, IndexError):
            continue
    return count

def can_user_start_new_script(user_id):
    """Check if user can start a new script based on subscription"""
    if user_id in admin_ids or user_id == OWNER_ID:
        return True
    
    sub_info = get_user_subscription_info(user_id)
    if sub_info['type'] == 'free':
        # Free users can run only 1 script
        return get_user_active_script_count(user_id) < 1
    
    # Subscribed users can run multiple scripts based on their subscription type
    max_scripts = sub_info.get('limit', SUBSCRIBED_USER_LIMIT)
    return get_user_active_script_count(user_id) < max_scripts

def generate_request_id():
    """Generate a unique request ID"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def save_subscription_request(request_id, user_id, sub_type, status='pending'):
    """Save subscription request to database"""
    with sqlite3.connect(DATABASE_PATH, check_same_thread=False) as conn:
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute('''INSERT OR REPLACE INTO subscription_requests 
                     (request_id, user_id, sub_type, status, timestamp, payment_proof, admin_notes) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (request_id, user_id, sub_type, status, timestamp, '', ''))
        conn.commit()
        subscription_requests[request_id] = {
            'user_id': user_id,
            'type': sub_type,
            'status': status,
            'timestamp': timestamp,
            'payment_proof': '',
            'admin_notes': ''
        }

def update_subscription_request(request_id, status, payment_proof='', admin_notes=''):
    """Update subscription request status"""
    with sqlite3.connect(DATABASE_PATH, check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute('''UPDATE subscription_requests 
                     SET status=?, payment_proof=?, admin_notes=? 
                     WHERE request_id=?''',
                  (status, payment_proof, admin_notes, request_id))
        conn.commit()
        if request_id in subscription_requests:
            subscription_requests[request_id]['status'] = status
            if payment_proof:
                subscription_requests[request_id]['payment_proof'] = payment_proof
            if admin_notes:
                subscription_requests[request_id]['admin_notes'] = admin_notes

def get_pending_requests():
    """Get all pending subscription requests"""
    pending = []
    for req_id, data in subscription_requests.items():
        if data['status'] == 'pending':
            pending.append((req_id, data))
    return pending

def save_subscription(user_id, sub_type, duration_days):
    """Save user subscription"""
    expiry = datetime.now() + timedelta(days=duration_days)
    bot_limit = SUBSCRIPTION_TYPES[sub_type]['limit']
    
    with sqlite3.connect(DATABASE_PATH, check_same_thread=False) as conn:
        c = conn.cursor()
        expiry_str = expiry.isoformat()
        c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry, sub_type, bot_limit) VALUES (?, ?, ?, ?)',
                  (user_id, expiry_str, sub_type, bot_limit))
        conn.commit()
        
    user_subscriptions[user_id] = {
        'expiry': expiry,
        'type': sub_type,
        'bot_limit': bot_limit
    }
    logger.info(f"Subscription activated for user {user_id}: {sub_type} until {expiry}")

def remove_subscription(user_id):
    """Remove user subscription"""
    with sqlite3.connect(DATABASE_PATH, check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
        conn.commit()
        if user_id in user_subscriptions:
            del user_subscriptions[user_id]
        logger.info(f"Subscription removed for user {user_id}")

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                logger.warning(f"Process {script_info['process'].pid} for {script_key} not running. Cleaning up.")
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try:
                        script_info['log_file'].close()
                    except Exception as log_e:
                        logger.error(f"Error closing log file during zombie cleanup {script_key}: {log_e}")
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            logger.warning(f"Process for {script_key} not found. Cleaning up.")
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try:
                    script_info['log_file'].close()
                except Exception as log_e:
                    logger.error(f"Error closing log file during cleanup: {log_e}")
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Error checking process status for {script_key}: {e}", exc_info=True)
            return False
    return False

def kill_process_tree(process_info):
    """Kill a process and all its children"""
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A')
    
    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
                logger.info(f"Closed log file for {script_key}")
            except Exception as log_e:
                logger.error(f"Error closing log file during kill for {script_key}: {log_e}")

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    
                    for child in children:
                        try:
                            child.terminate()
                        except:
                            try:
                                child.kill()
                            except:
                                pass
                    
                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        try:
                            p.kill()
                        except:
                            pass
                    
                    try:
                        parent.terminate()
                        try:
                            parent.wait(timeout=1)
                        except:
                            parent.kill()
                    except:
                        pass
                except:
                    pass
    except Exception as e:
        logger.error(f"Error killing process tree for {script_key}: {e}")

# --- Database Operations ---
DB_LOCK = threading.Lock()

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
            logger.info(f"Saved file '{file_name}' ({file_type}) for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving file for user {user_id}, {file_name}: {e}")
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]:
                    del user_files[user_id]
            logger.info(f"Removed file '{file_name}' for user {user_id} from DB")
        except Exception as e:
            logger.error(f"Error removing file for {user_id}, {file_name}: {e}")
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
            logger.info(f"Added active user {user_id}")
        except Exception as e:
            logger.error(f"Error adding active user {user_id}: {e}")
        finally:
            conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id)
            logger.info(f"Added admin {admin_id}")
        except Exception as e:
            logger.error(f"Error adding admin {admin_id}: {e}")
        finally:
            conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        logger.warning("Attempted to remove OWNER_ID from admins.")
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
            conn.commit()
            if c.rowcount > 0:
                admin_ids.discard(admin_id)
                logger.info(f"Removed admin {admin_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing admin {admin_id}: {e}")
            return False
        finally:
            conn.close()

# --- Menu Creation ---
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
        types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'),
        types.InlineKeyboardButton('💳 Subscription', callback_data='subscription_info'),
        types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]

    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Manage Subscriptions', callback_data='manage_subscriptions'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                                     callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('🟢 Run All Scripts', callback_data='run_all_scripts'),
            types.InlineKeyboardButton('📋 Pending Requests', callback_data='pending_requests')
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], admin_buttons[0])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[2], admin_buttons[5])
        markup.add(admin_buttons[4])
        markup.add(admin_buttons[6])
        markup.add(buttons[4], buttons[5])
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3])
        markup.add(types.InlineKeyboardButton('📊 Statistics', callback_data='stats'))
        markup.add(buttons[4], buttons[5])
    return markup

def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row_buttons_text in layout_to_use:
        markup.add(*[types.KeyboardButton(text) for text in row_buttons_text])
    return markup

def create_control_buttons(script_owner_id, file_name, is_running=True):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.row(
            types.InlineKeyboardButton("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    markup.add(types.InlineKeyboardButton("🔙 Back to Files", callback_data='check_files'))
    return markup

def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add Admin', callback_data='add_admin'),
        types.InlineKeyboardButton('➖ Remove Admin', callback_data='remove_admin')
    )
    markup.row(types.InlineKeyboardButton('📋 List Admins', callback_data='list_admins'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_subscription_plans_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"📦 Basic - 3 Bots (50 BDT)", callback_data='sub_basic'),
        types.InlineKeyboardButton(f"⭐ Premium - 5 Bots (100 BDT)", callback_data='sub_premium'),
        types.InlineKeyboardButton(f"👑 Monthly - Unlimited (200 BDT)", callback_data='sub_monthly'),
        types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main')
    )
    return markup

def create_pending_requests_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    pending = get_pending_requests()
    if not pending:
        markup.add(types.InlineKeyboardButton("📭 No pending requests", callback_data='noop'))
    else:
        for req_id, data in pending:
            user_id = data['user_id']
            sub_type = data['type']
            markup.add(types.InlineKeyboardButton(
                f"👤 {user_id} - {sub_type}", 
                callback_data=f'req_{req_id}'
            ))
    markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
    return markup

# --- Automatic Package Installation ---
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'flask': 'Flask',
    'psutil': 'psutil',
    'sqlite3': None,
    'json': None,
    'datetime': None,
    'os': None,
    'sys': None,
    're': None,
    'time': None,
    'threading': None,
    'subprocess': None,
    'zipfile': None,
    'tempfile': None,
    'shutil': None,
    'atexit': None,
    'random': None,
    'string': None,
}

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        logger.info(f"Module '{module_name}' is core. Skipping pip install.")
        return False
    try:
        bot.reply_to(message, f"🐍 Module `{module_name}` not found. Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Package `{package_name}` installed.", parse_mode='Markdown')
            return True
        else:
            bot.reply_to(message, f"❌ Failed to install `{package_name}`. Check logs.", parse_mode='Markdown')
            return False
    except Exception as e:
        logger.error(f"Error installing {package_name}: {e}")
        bot.reply_to(message, f"❌ Error installing `{package_name}`: {str(e)}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Node package `{module_name}` not found. Installing locally...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Node package `{module_name}` installed.", parse_mode='Markdown')
            return True
        else:
            bot.reply_to(message, f"❌ Failed to install Node package `{module_name}`.", parse_mode='Markdown')
            return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ 'npm' not found. Ensure Node.js is installed.")
        return False
    except Exception as e:
        logger.error(f"Error installing npm package {module_name}: {e}")
        bot.reply_to(message, f"❌ Error installing Node package: {str(e)}")
        return False

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    """Run Python script with subscription-based limits"""
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        return

    # Check if user can start new script based on subscription
    if not can_user_start_new_script(script_owner_id):
        sub_info = get_user_subscription_info(script_owner_id)
        if sub_info['type'] == 'free':
            bot.reply_to(message_obj_for_reply, 
                         "❌ আপনি ফ্রি ইউজার! শুধুমাত্র ১টি স্ক্রিপ্ট চালাতে পারেন।\n"
                         "💳 সাবস্ক্রাইব করতে `/subscription` কমান্ড ব্যবহার করুন।")
        else:
            bot.reply_to(message_obj_for_reply, 
                         f"❌ আপনার সাবস্ক্রিপশনে সর্বোচ্চ {sub_info['limit']}টি স্ক্রিপ্ট চালাতে পারেন!\n"
                         f"আপনি ইতিমধ্যে {get_user_active_script_count(script_owner_id)} টি চালাচ্ছেন।")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run Python script: {script_path} (Key: {script_key}) for user {script_owner_id}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Error: Script '{file_name}' not found!")
            logger.error(f"Script not found: {script_path} for user {script_owner_id}")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_command = [sys.executable, script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            bot.reply_to(message_obj_for_reply, f"🔄 Install successful. Retrying '{file_name}'...")
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ Install failed. Cannot run '{file_name}'.")
                            return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"❌ Error in script pre-check:\n```\n{error_summary}\n```", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                logger.info("Python Pre-check timed out. Proceeding to long run.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except Exception as e:
                logger.error(f"Error in pre-check: {e}")
                bot.reply_to(message_obj_for_reply, f"❌ Error in script pre-check: {str(e)}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()

        logger.info(f"Starting long-running Python process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to open log file '{log_file_path}': {e}")
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file: {e}")
            return
        
        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            process = subprocess.Popen(
                [sys.executable, script_path],
                cwd=user_folder,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags,
                encoding='utf-8',
                errors='ignore'
            )
            
            logger.info(f"Started Python process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process,
                'log_file': log_file,
                'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(),
                'user_folder': user_folder,
                'type': 'py',
                'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ Python script '{file_name}' started! (PID: {process.pid})")
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            logger.error(f"Error starting script: {e}")
            bot.reply_to(message_obj_for_reply, f"❌ Error starting script: {str(e)}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        logger.error(f"Error in run_script: {e}")
        bot.reply_to(message_obj_for_reply, f"❌ Unexpected error: {str(e)}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    """Run JS script with subscription-based limits"""
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts. Check logs.")
        return

    # Check if user can start new script based on subscription
    if not can_user_start_new_script(script_owner_id):
        sub_info = get_user_subscription_info(script_owner_id)
        if sub_info['type'] == 'free':
            bot.reply_to(message_obj_for_reply, 
                         "❌ আপনি ফ্রি ইউজার! শুধুমাত্র ১টি স্ক্রিপ্ট চালাতে পারেন।\n"
                         "💳 সাবস্ক্রাইব করতে `/subscription` কমান্ড ব্যবহার করুন।")
        else:
            bot.reply_to(message_obj_for_reply, 
                         f"❌ আপনার সাবস্ক্রিপশনে সর্বোচ্চ {sub_info['limit']}টি স্ক্রিপ্ট চালাতে পারেন!\n"
                         f"আপনি ইতিমধ্যে {get_user_active_script_count(script_owner_id)} টি চালাচ্ছেন।")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run JS script: {script_path} (Key: {script_key}) for user {script_owner_id}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Error: Script '{file_name}' not found!")
            logger.error(f"JS Script not found: {script_path} for user {script_owner_id}")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_command = ['node', script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                bot.reply_to(message_obj_for_reply, f"🔄 NPM Install successful. Retrying '{file_name}'...")
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"❌ Error in script pre-check:\n```\n{error_summary}\n```", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                logger.info("JS Pre-check timed out. Proceeding to long run.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, "❌ 'node' not found. Ensure Node.js is installed.")
                return
            except Exception as e:
                logger.error(f"Error in JS pre-check: {e}")
                bot.reply_to(message_obj_for_reply, f"❌ Error in script pre-check: {str(e)}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()

        logger.info(f"Starting long-running JS process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to open log file '{log_file_path}': {e}")
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file: {e}")
            return
        
        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            process = subprocess.Popen(
                ['node', script_path],
                cwd=user_folder,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags,
                encoding='utf-8',
                errors='ignore'
            )
            
            logger.info(f"Started JS process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process,
                'log_file': log_file,
                'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(),
                'user_folder': user_folder,
                'type': 'js',
                'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            if log_file and not log_file.closed:
                log_file.close()
            bot.reply_to(message_obj_for_reply, "❌ 'node' not found. Ensure Node.js is installed.")
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            logger.error(f"Error starting JS script: {e}")
            bot.reply_to(message_obj_for_reply, f"❌ Error starting script: {str(e)}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        logger.error(f"Error in run_js_script: {e}")
        bot.reply_to(message_obj_for_reply, f"❌ Unexpected error: {str(e)}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

# --- File Handling ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)

        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"🔄 Installing Python dependencies...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Python dependencies installed.")
            except Exception as e:
                bot.reply_to(message, f"❌ Failed to install Python dependencies: {str(e)}")
                return

        if pkg_json:
            bot.reply_to(message, f"🔄 Installing Node dependencies...")
            try:
                command = ['npm', 'install']
                subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Node dependencies installed.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ 'npm' not found. Cannot install Node dependencies.")
                return
            except Exception as e:
                bot.reply_to(message, f"❌ Failed to install Node dependencies: {str(e)}")
                return

        main_script_name = None
        file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        
        for p in preferred_py:
            if p in py_files:
                main_script_name = p
                file_type = 'py'
                break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files:
                    main_script_name = p
                    file_type = 'js'
                    break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]
                file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]
                file_type = 'js'
        
        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!")
            return

        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            elif os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(src_path, dest_path)

        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ Files extracted. Starting main script: `{main_script_name}`...", parse_mode='Markdown')

        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"❌ Invalid/corrupted ZIP: {e}")
    except Exception as e:
        logger.error(f"Error processing zip: {e}")
        bot.reply_to(message, f"❌ Error processing zip: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing Python file: {e}")
        bot.reply_to(message, f"❌ Error processing Python file: {str(e)}")

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing JS file: {e}")
        bot.reply_to(message, f"❌ Error processing JS file: {str(e)}")

# --- Logic Functions ---
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin. Try later.")
        return

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = f"🎉 New user!\n👤 Name: {user_name}\n✳️ User: @{user_username or 'N/A'}\n🆔 ID: `{user_id}`"
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}")

    sub_info = get_user_subscription_info(user_id)
    file_limit = sub_info['limit']
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    
    if user_id == OWNER_ID:
        user_status = "👑 Owner"
    elif user_id in admin_ids:
        user_status = "🛡️ Admin"
    elif sub_info['type'] != 'free':
        expiry = sub_info.get('expiry')
        if expiry and expiry > datetime.now():
            days_left = (expiry - datetime.now()).days
            user_status = f"⭐ {sub_info['type'].title()} - {days_left} days left"
        else:
            user_status = "🆓 Free User (Expired)"
    else:
        user_status = "🆓 Free User"

    welcome_msg = (f"〽️ Welcome, {user_name}!\n\n"
                   f"🆔 ID: `{user_id}`\n"
                   f"✳️ Username: `@{user_username or 'Not set'}`\n"
                   f"🔰 Status: {user_status}\n"
                   f"📁 Files: {current_files} / {limit_str}\n"
                   f"🤖 Running Scripts: {get_user_active_script_count(user_id)}\n\n"
                   f"💳 Subscription Plans:\n"
                   f"📦 Basic - 3 Bots (50 BDT)\n"
                   f"⭐ Premium - 5 Bots (100 BDT)\n"
                   f"👑 Monthly - Unlimited (200 BDT)\n\n"
                   f"Type /subscription to subscribe!")

    bot.send_message(chat_id, welcome_msg, reply_markup=create_reply_keyboard_main_menu(user_id), parse_mode='Markdown')

def _logic_subscription(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Check if user already has subscription
    sub_info = get_user_subscription_info(user_id)
    if sub_info['type'] != 'free':
        expiry = sub_info.get('expiry')
        if expiry and expiry > datetime.now():
            days_left = (expiry - datetime.now()).days
            bot.send_message(chat_id, 
                f"✅ আপনার সক্রিয় সাবস্ক্রিপশন রয়েছে!\n"
                f"📦 Type: {sub_info['type'].title()}\n"
                f"⏳ Expires: {expiry.strftime('%Y-%m-%d %H:%M')}\n"
                f"📅 Days left: {days_left}\n"
                f"🤖 Max Bots: {sub_info['limit']}\n\n"
                f"আপনি চাইলে নতুন সাবস্ক্রিপশন নিতে পারেন।",
                reply_markup=create_subscription_plans_markup())
        else:
            bot.send_message(chat_id, 
                "⚠️ আপনার সাবস্ক্রিপশন মেয়াদ শেষ হয়েছে!\n"
                "দয়া করে নতুন সাবস্ক্রিপশন নিন।",
                reply_markup=create_subscription_plans_markup())
    else:
        bot.send_message(chat_id, 
            "💳 সাবস্ক্রিপশন প্ল্যান:\n\n"
            "📦 Basic - 3 Bots (50 BDT)\n"
            "⭐ Premium - 5 Bots (100 BDT)\n"
            "👑 Monthly - Unlimited (200 BDT)\n\n"
            "পেমেন্ট করার পর অ্যাডমিনকে অনুমোদন দিতে হবে।\n"
            "নিচের বাটন থেকে আপনার পছন্দের প্ল্যান সিলেক্ট করুন:",
            reply_markup=create_subscription_plans_markup())

def _logic_pending_requests(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    
    pending = get_pending_requests()
    if not pending:
        bot.reply_to(message, "📭 No pending subscription requests.")
        return
    
    bot.reply_to(message, 
        "📋 Pending Subscription Requests:\n"
        "Click on a request to approve/reject:",
        reply_markup=create_pending_requests_markup())

def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 Your files:\n\n(No files uploaded yet)")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time = time.time()
    wait_msg = bot.reply_to(message, "🏃 Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        
        sub_info = get_user_subscription_info(user_id)
        if user_id == OWNER_ID:
            user_level = "👑 Owner"
        elif user_id in admin_ids:
            user_level = "🛡️ Admin"
        elif sub_info['type'] != 'free':
            user_level = f"⭐ {sub_info['type'].title()}"
        else:
            user_level = "🆓 Free User"
        
        speed_msg = (f"⚡ Bot Speed & Status:\n\n"
                     f"⏱️ Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     f"👤 Your Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error during speed test: {e}")
        bot.edit_message_text("❌ Error during speed test.", chat_id, wait_msg.message_id)

def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "Click to contact Owner:", reply_markup=markup)

def _logic_statistics(message):
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files = sum(len(files) for files in user_files.values())
    total_requests = len(subscription_requests)
    pending_requests = len(get_pending_requests())
    
    running_bots = 0
    for script_key, script_info in list(bot_scripts.items()):
        try:
            owner_id = int(script_key.split('_')[0])
            if is_bot_running(owner_id, script_info.get('file_name', '')):
                running_bots += 1
        except:
            pass
    
    stats_msg = (f"📊 Bot Statistics:\n\n"
                 f"👥 Total Users: {total_users}\n"
                 f"📂 Total Files: {total_files}\n"
                 f"🟢 Running Bots: {running_bots}\n"
                 f"💳 Total Sub Requests: {total_requests}\n"
                 f"⏳ Pending Requests: {pending_requests}\n"
                 f"🔒 Bot Status: {'🔴 Locked' if bot_locked else '🟢 Unlocked'}")
    
    bot.reply_to(message, stats_msg)

def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    msg = bot.reply_to(message, "📢 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Broadcast cancelled.")
        return
    
    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_broadcast_{message.message_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
    )
    
    preview = message.text[:500] if message.text else "(Media message)"
    bot.reply_to(message, 
        f"⚠️ Confirm Broadcast:\n\n```\n{preview}\n```\nTo **{target_count}** users.",
        reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
        return
    
    try:
        original_message = call.message.reply_to_message
        if not original_message:
            raise ValueError("Could not retrieve original message.")
        
        broadcast_text = original_message.text
        broadcast_photo = None
        broadcast_video = None
        
        if original_message.photo:
            broadcast_photo = original_message.photo[-1].file_id
        elif original_message.video:
            broadcast_video = original_message.video.file_id
        elif not broadcast_text:
            raise ValueError("Message has no text or supported media.")
        
        bot.answer_callback_query(call.id, "🚀 Starting broadcast...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...",
                            call.message.chat.id, call.message.message_id, reply_markup=None)
        
        thread = threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo, broadcast_video,
            original_message.caption if (broadcast_photo or broadcast_video) else None,
            call.message.chat.id))
        thread.start()
    except Exception as e:
        logger.error(f"Error in broadcast confirm: {e}")
        bot.edit_message_text(f"❌ Error: {str(e)}", call.message.chat.id, call.message.message_id)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)

def execute_broadcast(text, photo_id, video_id, caption, admin_chat_id):
    sent = 0
    failed = 0
    for user_id in list(active_users):
        try:
            if text:
                bot.send_message(user_id, text, parse_mode='Markdown')
            elif photo_id:
                bot.send_photo(user_id, photo_id, caption=caption)
            elif video_id:
                bot.send_video(user_id, video_id, caption=caption)
            sent += 1
        except:
            failed += 1
        time.sleep(0.1)
    
    result_msg = f"📢 Broadcast Complete!\n✅ Sent: {sent}\n❌ Failed: {failed}"
    bot.send_message(admin_chat_id, result_msg)

def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "👑 Admin Panel", reply_markup=create_admin_panel())

def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        msg_obj = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(message_or_call.message.chat.id, text, **kwargs)
        msg_obj = message_or_call.message
    else:
        return
    
    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin permissions required.")
        return
    
    reply_func("⏳ Starting all user scripts...")
    started = 0
    
    for target_user_id, files in user_files.items():
        for file_name, file_type in files:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(get_user_folder(target_user_id), file_name)
                if os.path.exists(file_path):
                    if file_type == 'py':
                        threading.Thread(target=run_script, args=(file_path, target_user_id, get_user_folder(target_user_id), file_name, msg_obj)).start()
                        started += 1
                    elif file_type == 'js':
                        threading.Thread(target=run_js_script, args=(file_path, target_user_id, get_user_folder(target_user_id), file_name, msg_obj)).start()
                        started += 1
                time.sleep(0.5)
    
    reply_func(f"✅ Started {started} scripts.")

def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    bot.reply_to(message, f"🔒 Bot has been {status}.")

# --- Command Handlers ---
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    _logic_send_welcome(message)

@bot.message_handler(commands=['subscription'])
def command_subscription(message):
    _logic_subscription(message)

@bot.message_handler(commands=['pending'])
def command_pending(message):
    _logic_pending_requests(message)

@bot.message_handler(commands=['status'])
def command_status(message):
    _logic_statistics(message)

BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics,
    "💳 Subscription": _logic_subscription,
    "💳 Subscriptions": _logic_subscription,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "🟢 Running All Code": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
    "📋 Pending Requests": _logic_pending_requests,
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func:
        logic_func(message)

def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
    bot.reply_to(message, "Visit our Updates Channel:", reply_markup=markup)

def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return
    
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{file_limit}) reached. Delete files first.")
        return
    bot.reply_to(message, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")

@bot.message_handler(content_types=['document'])
def handle_file_upload(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return
    
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{file_limit}) reached.")
        return
    
    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "⚠️ No file name.")
        return
    
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Only `.py`, `.js`, `.zip` allowed.")
        return
    
    max_size = 20 * 1024 * 1024
    if doc.file_size > max_size:
        bot.reply_to(message, f"⚠️ File too large (Max: 20 MB).")
        return
    
    try:
        download_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info = bot.get_file(doc.file_id)
        file_content = bot.download_file(file_info.file_path)
        bot.edit_message_text(f"✅ Downloaded. Processing...", chat_id, download_msg.message_id)
        
        user_folder = get_user_folder(user_id)
        
        if file_ext == '.zip':
            handle_zip_file(file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            if file_ext == '.py':
                handle_py_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.js':
                handle_js_file(file_path, user_id, user_folder, file_name, message)
    
    except Exception as e:
        logger.error(f"Error handling file: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

# --- Callback Query Handlers ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']:
        bot.answer_callback_query(call.id, "⚠️ Bot locked.", show_alert=True)
        return
    
    try:
        if data == 'upload':
            _logic_upload_file(call.message)
            bot.answer_callback_query(call.id)
        
        elif data == 'check_files':
            _logic_check_files(call.message)
            bot.answer_callback_query(call.id)
        
        elif data == 'speed':
            _logic_bot_speed(call.message)
            bot.answer_callback_query(call.id)
        
        elif data == 'stats':
            _logic_statistics(call.message)
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=create_main_menu_inline(user_id))
            except:
                pass
        
        elif data == 'subscription_info':
            _logic_subscription(call.message)
            bot.answer_callback_query(call.id)
        
        elif data == 'back_to_main':
            _logic_send_welcome(call.message)
            bot.answer_callback_query(call.id)
        
        elif data.startswith('sub_'):
            sub_type = data.replace('sub_', '')
            if sub_type in SUBSCRIPTION_TYPES:
                handle_subscription_request(call, sub_type)
        
        elif data == 'manage_subscriptions':
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, 
                "💳 Manage Subscriptions:\n"
                "Use /subscription to view user subscriptions.\n"
                "Use /pending to view pending requests.")
        
        elif data == 'pending_requests':
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            _logic_pending_requests(call.message)
            bot.answer_callback_query(call.id)
        
        elif data.startswith('req_'):
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            req_id = data.replace('req_', '')
            handle_request_detail(call, req_id)
        
        elif data.startswith('approve_'):
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            req_id = data.replace('approve_', '')
            handle_approve_request(call, req_id)
        
        elif data.startswith('reject_'):
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            req_id = data.replace('reject_', '')
            handle_reject_request(call, req_id)
        
        elif data == 'admin_panel':
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            _logic_admin_panel(call.message)
            bot.answer_callback_query(call.id)
        
        elif data == 'add_admin':
            if user_id != OWNER_ID:
                bot.answer_callback_query(call.id, "⚠️ Owner only.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to promote to Admin:\n/cancel to abort.")
            bot.register_next_step_handler(msg, process_add_admin)
        
        elif data == 'remove_admin':
            if user_id != OWNER_ID:
                bot.answer_callback_query(call.id, "⚠️ Owner only.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to remove from Admin:\n/cancel to abort.")
            bot.register_next_step_handler(msg, process_remove_admin)
        
        elif data == 'list_admins':
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            admin_list = "\n".join(f"- `{aid}` {'(Owner)' if aid == OWNER_ID else ''}" for aid in sorted(admin_ids))
            bot.send_message(call.message.chat.id, f"👑 Current Admins:\n\n{admin_list}", parse_mode='Markdown')
        
        elif data == 'lock_bot':
            global bot_locked
            bot_locked = True
            bot.answer_callback_query(call.id, "🔒 Bot locked.")
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=create_main_menu_inline(user_id))
            except:
                pass
        
        elif data == 'unlock_bot':
            global bot_locked
            bot_locked = False
            bot.answer_callback_query(call.id, "🔓 Bot unlocked.")
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=create_main_menu_inline(user_id))
            except:
                pass
        
        elif data == 'run_all_scripts':
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            _logic_run_all_scripts(call)
        
        elif data == 'broadcast':
            if user_id not in admin_ids:
                bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
                return
            _logic_broadcast_init(call.message)
            bot.answer_callback_query(call.id)
        
        elif data.startswith('confirm_broadcast_'):
            handle_confirm_broadcast(call)
        
        elif data == 'cancel_broadcast':
            handle_cancel_broadcast(call)
        
        elif data.startswith('file_'):
            handle_file_control(call)
        
        elif data.startswith('start_'):
            handle_start_script(call)
        
        elif data.startswith('stop_'):
            handle_stop_script(call)
        
        elif data.startswith('restart_'):
            handle_restart_script(call)
        
        elif data.startswith('delete_'):
            handle_delete_script(call)
        
        elif data.startswith('logs_'):
            handle_show_logs(call)
        
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
    
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        bot.answer_callback_query(call.id, "Error processing request.", show_alert=True)

# --- Subscription Handlers ---
def handle_subscription_request(call, sub_type):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    price = SUBSCRIPTION_TYPES[sub_type]['price']
    bot_limit = SUBSCRIPTION_TYPES[sub_type]['limit']
    duration = SUBSCRIPTION_TYPES[sub_type]['duration']
    
    # Generate unique request ID
    request_id = generate_request_id()
    
    # Save request to database
    save_subscription_request(request_id, user_id, sub_type)
    
    payment_info = (
        f"💳 Subscription Request Submitted!\n\n"
        f"📦 Plan: {sub_type.title()}\n"
        f"💰 Price: {price} BDT\n"
        f"🤖 Bots: {bot_limit}\n"
        f"📅 Duration: {duration} days\n"
        f"🆔 Request ID: `{request_id}`\n\n"
        f"📝 Please send payment to:\n"
        f"📱 bKash/Nagad: `{PAYMENT_NUMBER}`\n"
        f"📌 Reference: `{PAYMENT_REFERENCE}`\n\n"
        f"⚠️ After payment, send the transaction ID to admin.\n"
        f"Admin will approve your subscription."
    )
    
    # Notify admin
    admin_notification = (
        f"📢 New Subscription Request!\n\n"
        f"👤 User: `{user_id}`\n"
        f"📦 Plan: {sub_type.title()}\n"
        f"💰 Price: {price} BDT\n"
        f"🆔 Request ID: `{request_id}`\n\n"
        f"Use /pending to view and process."
    )
    
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, admin_notification, parse_mode='Markdown')
        except:
            pass
    
    bot.send_message(chat_id, payment_info, parse_mode='Markdown')
    bot.answer_callback_query(call.id, "✅ Request submitted! Check instructions.")

def handle_request_detail(call, request_id):
    data = subscription_requests.get(request_id)
    if not data:
        bot.answer_callback_query(call.id, "❌ Request not found.", show_alert=True)
        return
    
    user_id = data['user_id']
    sub_type = data['type']
    status = data['status']
    timestamp = data.get('timestamp', 'Unknown')
    proof = data.get('payment_proof', 'No proof provided')
    notes = data.get('admin_notes', '')
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    if status == 'pending':
        markup.row(
            types.InlineKeyboardButton("✅ Approve", callback_data=f'approve_{request_id}'),
            types.InlineKeyboardButton("❌ Reject", callback_data=f'reject_{request_id}')
        )
    markup.add(types.InlineKeyboardButton("🔙 Back to Requests", callback_data='pending_requests'))
    
    details = (f"📋 Request Details:\n\n"
               f"🆔 ID: `{request_id}`\n"
               f"👤 User: `{user_id}`\n"
               f"📦 Plan: {sub_type.title()}\n"
               f"📅 Submitted: {timestamp}\n"
               f"📌 Status: {status.upper()}\n"
               f"💳 Payment Proof: {proof[:50]}...\n"
               f"📝 Notes: {notes or 'None'}")
    
    bot.send_message(call.message.chat.id, details, parse_mode='Markdown', reply_markup=markup)
    bot.answer_callback_query(call.id)

def handle_approve_request(call, request_id):
    data = subscription_requests.get(request_id)
    if not data:
        bot.answer_callback_query(call.id, "❌ Request not found.", show_alert=True)
        return
    
    user_id = data['user_id']
    sub_type = data['type']
    
    # Update request status
    update_subscription_request(request_id, 'approved', admin_notes='Approved by admin')
    
    # Activate subscription
    duration = SUBSCRIPTION_TYPES[sub_type]['duration']
    save_subscription(user_id, sub_type, duration)
    
    # Notify user
    try:
        bot.send_message(user_id, 
            f"🎉 Congratulations! Your subscription has been approved!\n\n"
            f"📦 Plan: {sub_type.title()}\n"
            f"🤖 You can now host up to {SUBSCRIPTION_TYPES[sub_type]['limit']} bots.\n"
            f"📅 Duration: {duration} days\n\n"
            f"Thank you for subscribing! 🚀")
    except:
        pass
    
    bot.answer_callback_query(call.id, "✅ Subscription approved!")
    bot.edit_message_text("✅ Request approved and subscription activated.",
                         call.message.chat.id, call.message.message_id)
    
    # Refresh pending requests
    _logic_pending_requests(call.message)

def handle_reject_request(call, request_id):
    data = subscription_requests.get(request_id)
    if not data:
        bot.answer_callback_query(call.id, "❌ Request not found.", show_alert=True)
        return
    
    user_id = data['user_id']
    
    update_subscription_request(request_id, 'rejected', admin_notes='Rejected by admin')
    
    try:
        bot.send_message(user_id, 
            f"❌ Your subscription request has been rejected.\n\n"
            f"Please contact admin for more information.\n"
            f"📞 Contact: {YOUR_USERNAME}")
    except:
        pass
    
    bot.answer_callback_query(call.id, "❌ Request rejected.")
    bot.edit_message_text("❌ Request rejected.",
                         call.message.chat.id, call.message.message_id)
    
    _logic_pending_requests(call.message)

# --- File Control Handlers ---
def handle_file_control(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        user_id = call.from_user.id
        
        if user_id != script_owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        
        is_running = is_bot_running(script_owner_id, file_name)
        markup = create_control_buttons(script_owner_id, file_name, is_running)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Error in file control: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def handle_start_script(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        user_id = call.from_user.id
        
        if user_id != script_owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        
        if not can_user_start_new_script(script_owner_id):
            sub_info = get_user_subscription_info(script_owner_id)
            if sub_info['type'] == 'free':
                bot.answer_callback_query(call.id, 
                    "❌ Free users can run only 1 script!\n"
                    "Subscribe to run more.", show_alert=True)
            else:
                bot.answer_callback_query(call.id, 
                    f"❌ Max {sub_info['limit']} scripts allowed.\n"
                    f"You already have {get_user_active_script_count(script_owner_id)} running.", show_alert=True)
            return
        
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            return
        
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ File missing. Re-upload.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            return
        
        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, "⚠️ Already running.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, f"⏳ Starting...")
        
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        markup = create_control_buttons(script_owner_id, file_name, is_now_running)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in start script: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def handle_stop_script(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        user_id = call.from_user.id
        
        if user_id != script_owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        
        script_key = f"{script_owner_id}_{file_name}"
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]
        
        bot.answer_callback_query(call.id, "✅ Stopped.")
        markup = create_control_buttons(script_owner_id, file_name, False)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in stop script: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def handle_restart_script(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        user_id = call.from_user.id
        
        if user_id != script_owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            return
        
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "⚠️ File missing.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, f"🔄 Restarting...")
        
        # Stop if running
        script_key = f"{script_owner_id}_{file_name}"
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]
            time.sleep(0.5)
        
        # Start
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        markup = create_control_buttons(script_owner_id, file_name, is_now_running)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in restart script: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def handle_delete_script(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        user_id = call.from_user.id
        
        if user_id != script_owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        
        # Stop if running
        script_key = f"{script_owner_id}_{file_name}"
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]
        
        # Delete files
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(log_path):
            os.remove(log_path)
        
        remove_user_file_db(script_owner_id, file_name)
        
        bot.answer_callback_query(call.id, "🗑️ Deleted.")
        bot.edit_message_text(f"✅ Deleted: `{file_name}`", 
                            call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in delete script: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def handle_show_logs(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        user_id = call.from_user.id
        
        if user_id != script_owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return
        
        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, "⚠️ No logs found.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id)
        
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()
        
        if len(log_content) > 4000:
            log_content = log_content[-4000:]
            log_content = "...\n" + log_content
        
        bot.send_message(call.message.chat.id, 
            f"📜 Logs for `{file_name}`:\n```\n{log_content}\n```", 
            parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in show logs: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

# --- Admin Management ---
def process_add_admin(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        admin_id = int(message.text.strip())
        if admin_id in admin_ids:
            bot.reply_to(message, f"⚠️ User `{admin_id}` already Admin.")
            return
        add_admin_db(admin_id)
        bot.reply_to(message, f"✅ User `{admin_id}` promoted to Admin.")
        try:
            bot.send_message(admin_id, "🎉 You are now an Admin!")
        except:
            pass
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID.")
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

def process_remove_admin(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        admin_id = int(message.text.strip())
        if admin_id == OWNER_ID:
            bot.reply_to(message, "⚠️ Cannot remove Owner.")
            return
        if remove_admin_db(admin_id):
            bot.reply_to(message, f"✅ Admin `{admin_id}` removed.")
            try:
                bot.send_message(admin_id, "ℹ️ You are no longer an Admin.")
            except:
                pass
        else:
            bot.reply_to(message, f"⚠️ User `{admin_id}` not Admin.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID.")
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

# --- Cleanup ---
def cleanup():
    logger.warning("Shutting down. Cleaning up...")
    for script_key in list(bot_scripts.keys()):
        kill_process_tree(bot_scripts[script_key])
    logger.warning("Cleanup complete.")

atexit.register(cleanup)

# --- Main ---
if __name__ == '__main__':
    logger.info("="*40)
    logger.info("🤖 Bot Starting...")
    logger.info(f"Owner: {OWNER_ID}")
    logger.info(f"Admins: {admin_ids}")
    logger.info("="*40)
    
    keep_alive()
    
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)
