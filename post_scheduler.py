import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update
from database import AsyncSessionLocal
from models import PostQueue, Project, PublishedPost
from posters import TelegramPoster

logger = logging.getLogger(__name__)


class PostScheduler:
    """Планировщик публикации постов из очереди с соблюдением интервала."""
    
    def __init__(self, telegram_poster: TelegramPoster):
        self.telegram_poster = telegram_poster
        self._running = False

    async def start(self):
        self._running = True
        logger.info("🟢 PostScheduler started")
        
        while self._running:
            try:
                await self._check_and_publish()
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"PostScheduler error: {e}")
                await asyncio.sleep(60)

    async def _check_and_publish(self):
        """Публикует ОДИН пост за раз с проверкой интервала и активных часов."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PostQueue).where(
                    PostQueue.status == "pending",
                    PostQueue.scheduled_time <= datetime.utcnow()
                ).order_by(PostQueue.scheduled_time).limit(1)
            )
            queue_item = result.scalar_one_or_none()
        
        if not queue_item:
            return
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Project).where(Project.id == queue_item.project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                logger.warning(f"Project {queue_item.project_id} not found, skipping post {queue_item.id}")
                return
            
            # === ПРОВЕРКА АКТИВНЫХ ЧАСОВ ===
            msk_now = datetime.utcnow() + timedelta(hours=3)
            current_hour = msk_now.hour
            
            start_hour = project.active_hours_start
            end_hour = project.active_hours_end
            
            if end_hour != 24:
                if current_hour < start_hour or current_hour >= end_hour:
                    logger.info(
                        f"⏸️ Post {queue_item.id}: outside active hours "
                        f"({start_hour}:00-{end_hour}:00), current time: {current_hour}:{msk_now.minute:02d} MSK"
                    )
                    return
            
            # === ПРОВЕРКА ИНТЕРВАЛА ===
            result = await session.execute(
                select(PublishedPost).where(
                    PublishedPost.project_id == project.id
                ).order_by(PublishedPost.published_at.desc()).limit(1)
            )
            last_published = result.scalar_one_or_none()
            
            # post_interval_hours теперь хранит минуты
            interval_minutes = project.post_interval_hours
            
            if last_published and last_published.published_at:
                last_msk = last_published.published_at + timedelta(hours=3)
                elapsed = (msk_now - last_msk).total_seconds() / 60
                
                if elapsed < interval_minutes:
                    # Переносим пост вперёд
                    new_scheduled = last_published.published_at + timedelta(minutes=interval_minutes)
                    await session.execute(
                        update(PostQueue)
                        .where(PostQueue.id == queue_item.id)
                        .values(scheduled_time=new_scheduled)
                    )
                    await session.commit()
                    logger.info(
                        f"⏳ Post {queue_item.id} rescheduled: "
                        f"only {elapsed:.0f}min since last, need {interval_minutes}min "
                        f"→ moved to {(new_scheduled + timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')} MSK"
                    )
                    return
        
        # Публикуем
        try:
            logger.info(f"📤 Publishing post {queue_item.id} (scheduled: {queue_item.scheduled_time})")
            success = await self.telegram_poster.publish_post(queue_item)
            if success:
                logger.info(f"✅ Published post {queue_item.id}")
                
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Project).where(Project.id == queue_item.project_id)
                    )
                    db_project = result.scalar_one_or_none()
                    if db_project:
                        today = datetime.utcnow().date()
                        if db_project.last_reset and db_project.last_reset.date() < today:
                            db_project.posts_parsed_today = 0
                            db_project.posts_posted_today = 0
                            db_project.last_reset = datetime.utcnow()
                        db_project.posts_posted_today += 1
                        await session.commit()
            else:
                logger.warning(f"❌ Failed to publish post {queue_item.id}")
        except Exception as e:
            logger.error(f"Error publishing post {queue_item.id}: {e}")

    async def stop(self):
        self._running = False
        logger.info("🔴 PostScheduler stopped")