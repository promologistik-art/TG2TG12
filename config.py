import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
    
    # Идентификация клона
    BOT_TYPE = os.getenv("BOT_TYPE", "tg2tg")
    CLONE_ID = int(os.getenv("CLONE_ID", "1"))
    BOT_USERNAME = os.getenv("BOT_USERNAME", "")
    
    # Префикс для таблиц этого клона
    TABLE_PREFIX = f"tg{CLONE_ID}_"
    
    # PostgreSQL
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    # Пути
    SHARED_DIR = os.getenv("SHARED_DIR", "/app/shared")
    DATA_DIR = os.path.join(SHARED_DIR, "data")
    TEMP_DIR = os.path.join(SHARED_DIR, "temp")
    BACKUP_DIR = os.path.join(SHARED_DIR, "backups", f"{BOT_TYPE}_{CLONE_ID}")
    
    # Лимиты
    DEFAULT_MAX_PROJECTS = int(os.getenv("DEFAULT_MAX_PROJECTS", "1"))
    DEFAULT_MAX_SOURCES_PER_PROJECT = int(os.getenv("DEFAULT_MAX_SOURCES_PER_PROJECT", "3"))
    DEFAULT_CHECK_INTERVAL = int(os.getenv("DEFAULT_CHECK_INTERVAL", "60"))
    
    # Публикация
    DEFAULT_POST_INTERVAL_HOURS = int(os.getenv("DEFAULT_POST_INTERVAL_HOURS", "2"))
    MIN_POST_INTERVAL_MINUTES = int(os.getenv("MIN_POST_INTERVAL_MINUTES", "15"))
    DEFAULT_ACTIVE_HOURS_START = int(os.getenv("DEFAULT_ACTIVE_HOURS_START", "8"))
    DEFAULT_ACTIVE_HOURS_END = int(os.getenv("DEFAULT_ACTIVE_HOURS_END", "22"))
    
    SHOW_SOURCE_SIGNATURE = os.getenv("SHOW_SOURCE_SIGNATURE", "false").lower() == "true"
    
    TIMEZONE = "Europe/Moscow"
    
    # Таймауты
    SCRAPER_TIMEOUT = 30
    SCRAPER_RETRIES = 3
    SCRAPER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    BOT_CONNECT_TIMEOUT = int(os.getenv("BOT_CONNECT_TIMEOUT", "30"))
    BOT_READ_TIMEOUT = int(os.getenv("BOT_READ_TIMEOUT", "60"))
    BOT_WRITE_TIMEOUT = int(os.getenv("BOT_WRITE_TIMEOUT", "60"))

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL is required")

Config.validate()