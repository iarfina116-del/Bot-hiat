# app.py - Railway deployment entry point
from HOSTINGBOT import bot, keep_alive
import logging
import os
import threading
import time

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_bot():
    """ব্যাকগ্রাউন্ডে বট চালানোর জন্য"""
    while True:
        try:
            logger.info("🚀 Starting bot polling...")
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"❌ Bot polling error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logger.info("="*40)
    logger.info("🚀 Starting Bot on Railway...")
    logger.info("="*40)
    
    # Flask Keep-Alive চালু করুন (HOSTINGBOT থেকে)
    keep_alive()
    
    # বট পোলিং শুরু করুন
    try:
        bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
