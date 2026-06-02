import os
import logging
import json
import sqlite3
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text
from datetime import datetime, timedelta
from config import Config
from models import Base, User, Project

logger = logging.getLogger(__name__)

# Создаём папки для temp и backups
os.makedirs(Config.TEMP_DIR, exist_ok=True)
os.makedirs(Config.BACKUP_DIR, exist_ok=True)

DATABASE_URL = Config.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Кэш спарсенных URL
parsed_urls = {}


async def _migrate_from_sqlite():
    """
    Автоматическая миграция данных из SQLite в PostgreSQL.
    Ищет bot.db в текущей директории и /app/shared/data/.
    После миграции переименовывает файл в bot.db.migrated.
    """
    # Где искать старую БД
    search_paths = [
        "bot.db",
        os.path.join(Config.DATA_DIR, "bot.db"),
        os.path.join(Config.SHARED_DIR, "bot.db"),
        "/app/bot.db",
    ]
    
    sqlite_path = None
    for path in search_paths:
        if os.path.exists(path):
            sqlite_path = path
            break
    
    if not sqlite_path:
        logger.info("ℹ️ Старая SQLite БД не найдена — миграция не требуется")
        return False
    
    logger.info(f"🔍 Найдена старая БД: {sqlite_path}")
    
    # Проверяем, есть ли уже данные в PostgreSQL
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            logger.info("ℹ️ В PostgreSQL уже есть данные — миграция пропущена")
            # Переименовываем старый файл чтобы не мешал
            try:
                os.rename(sqlite_path, sqlite_path + ".migrated")
            except:
                pass
            return False
    
    # Читаем SQLite
    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Получаем список таблиц
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row["name"] for row in cursor.fetchall()]
        logger.info(f"📋 Таблицы SQLite: {tables}")
        
        total_rows = 0
        
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = [dict(row) for row in cursor.fetchall()]
                
                if not rows:
                    continue
                
                pg_table = f"{Config.TABLE_PREFIX}{table}"
                
                # Вставляем в PostgreSQL
                async with engine.begin() as pg_conn:
                    for row in rows:
                        clean_row = {}
                        for key, value in row.items():
                            if value is None:
                                clean_row[key] = None
                            elif isinstance(value, str) and (value.startswith("{") or value.startswith("[")):
                                try:
                                    clean_row[key] = json.loads(value)
                                except:
                                    clean_row[key] = value
                            else:
                                clean_row[key] = value
                        
                        columns = ", ".join(clean_row.keys())
                        placeholders = ", ".join([f":{k}" for k in clean_row.keys()])
                        
                        try:
                            await pg_conn.execute(
                                text(f"INSERT INTO {pg_table} ({columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"),
                                clean_row
                            )
                        except Exception as e:
                            logger.debug(f"  Пропущена строка в {table}: {e}")
                
                logger.info(f"  ✅ {table}: {len(rows)} строк")
                total_rows += len(rows)
                
            except Exception as e:
                logger.warning(f"  ⚠️ Таблица {table}: {e}")
        
        conn.close()
        
        # Переименовываем старый файл
        try:
            os.rename(sqlite_path, sqlite_path + ".migrated")
            logger.info(f"📁 Старая БД переименована: {sqlite_path}.migrated")
        except Exception as e:
            logger.warning(f"Не удалось переименовать: {e}")
        
        logger.info(f"🎉 Миграция завершена! Перенесено {total_rows} строк в PostgreSQL (префикс: {Config.TABLE_PREFIX})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}")
        return False


async def init_db():
    # Создаём таблицы в PostgreSQL
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Пробуем мигрировать данные из SQLite
    await _migrate_from_sqlite()
    
    # Создаём админа
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == Config.ADMIN_ID))
        admin = result.scalar_one_or_none()
        if not admin:
            admin = User(
                telegram_id=Config.ADMIN_ID, is_admin=True, tariff="unlimited",
                max_projects=999, max_sources_per_project=999,
                min_post_interval_minutes=1, min_check_interval_minutes=5,
                subscription_active=True,
                trial_ends_at=datetime.utcnow() + timedelta(days=36500)
            )
            session.add(admin)
            await session.commit()
            logger.info("Admin created")
        
        # Создаём дефолтный проект для админа
        result = await session.execute(
            select(Project).where(Project.user_id == Config.ADMIN_ID)
        )
        if not result.scalars().all():
            project = Project(user_id=Config.ADMIN_ID, name="Админский")
            session.add(project)
            await session.commit()
    
    logger.info(f"✅ Database initialized (prefix: {Config.TABLE_PREFIX})")


async def is_post_parsed(project_id: int, post_url: str) -> bool:
    cache_key = f"{project_id}:{post_url}"
    if cache_key in parsed_urls:
        return True
    async with AsyncSessionLocal() as session:
        from models import ParsedPost
        result = await session.execute(
            select(ParsedPost).where(
                ParsedPost.project_id == project_id,
                ParsedPost.post_url == post_url
            )
        )
        exists = result.scalar_one_or_none() is not None
        if exists:
            parsed_urls[cache_key] = True
        return exists


async def mark_post_parsed(project_id: int, source_channel_id: int, post_url: str):
    cache_key = f"{project_id}:{post_url}"
    parsed_urls[cache_key] = True
    async with AsyncSessionLocal() as session:
        from models import ParsedPost
        result = await session.execute(
            select(ParsedPost).where(
                ParsedPost.project_id == project_id,
                ParsedPost.post_url == post_url
            )
        )
        if result.scalar_one_or_none():
            return
        post = ParsedPost(
            project_id=project_id,
            source_channel_id=source_channel_id,
            post_url=post_url
        )
        session.add(post)
        try:
            await session.commit()
        except:
            await session.rollback()


async def clear_parsed_cache():
    count = len(parsed_urls)
    parsed_urls.clear()
    logger.info(f"🧹 Parsed URLs cache cleared ({count} entries)")