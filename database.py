import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text
from datetime import datetime, timedelta
from config import Config
from models import Base, User, Project, SourceChannel, TargetChannel, ParsedPost

logger = logging.getLogger(__name__)

os.makedirs(Config.TEMP_DIR, exist_ok=True)
os.makedirs(Config.BACKUP_DIR, exist_ok=True)

DATABASE_URL = Config.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Кэш спарсенных URL (словарь: key → True)
parsed_urls = {}


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
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
        
        result = await session.execute(
            select(Project).where(Project.user_id == Config.ADMIN_ID)
        )
        if not result.scalars().all():
            project = Project(user_id=Config.ADMIN_ID, name="Админский")
            session.add(project)
            await session.commit()
    
    logger.info(f"✅ Database initialized (prefix: {Config.TABLE_PREFIX})")


async def is_post_parsed(project_id: int, post_url: str) -> bool:
    """Проверяет, был ли пост уже спарсен (сначала кэш, потом БД)."""
    cache_key = f"{project_id}:{post_url}"
    if cache_key in parsed_urls:
        return True
    
    async with AsyncSessionLocal() as session:
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
    """Отмечает пост как спарсенный. Кэш обновляется только после успешного коммита."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ParsedPost).where(
                ParsedPost.project_id == project_id,
                ParsedPost.post_url == post_url
            )
        )
        if result.scalar_one_or_none():
            # Уже есть в БД — просто обновляем кэш
            cache_key = f"{project_id}:{post_url}"
            parsed_urls[cache_key] = True
            return
        
        post = ParsedPost(
            project_id=project_id,
            source_channel_id=source_channel_id,
            post_url=post_url
        )
        session.add(post)
        try:
            await session.commit()
            # Кэш обновляем ТОЛЬКО после успешного коммита
            cache_key = f"{project_id}:{post_url}"
            parsed_urls[cache_key] = True
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to mark post as parsed: {e}")


async def clear_parsed_cache():
    """Очищает кэш спарсенных URL'ов."""
    count = len(parsed_urls)
    parsed_urls.clear()
    logger.info(f"🧹 Parsed URLs cache cleared ({count} entries)")


async def get_active_projects():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Project).where(Project.is_active == True)
        )
        return result.scalars().all()


async def get_user_projects(telegram_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Project).where(
                Project.user_id == telegram_id,
                Project.is_active == True
            )
        )
        return result.scalars().all()


async def get_project_sources(project_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SourceChannel).where(
                SourceChannel.project_id == project_id,
                SourceChannel.is_active == True
            )
        )
        return result.scalars().all()


async def get_project_target(project_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TargetChannel).where(TargetChannel.project_id == project_id)
        )
        return result.scalar_one_or_none()