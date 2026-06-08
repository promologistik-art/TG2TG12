import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select, update
from database import AsyncSessionLocal, is_post_parsed, mark_post_parsed
from models import User, Project, SourceChannel, TargetChannel, PostQueue, PublishedPost
from scrapers import TelegramScraper
from posters import TelegramPoster
from utils import calculate_score, get_moscow_time
from config import Config

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, poster: TelegramPoster):
        self.poster = poster
        self._running = False
        self._tasks = {}
        self._last_daily_cleanup = None
        self._last_check = {}

    async def start(self):
        self._running = True
        logger.info("🟢 Scheduler started")
        
        while self._running:
            try:
                await self._check_projects()
                await self._check_daily_tasks()
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)

    async def _check_daily_tasks(self):
        now = get_moscow_time()
        if now.hour == 9 and now.minute == 0:
            today = now.date()
            if self._last_daily_cleanup != today:
                self._last_daily_cleanup = today
                from database import clear_parsed_cache
                await clear_parsed_cache()
                logger.info("🧹 Parsed URLs cache cleared (daily)")

    async def _check_projects(self):
        now = datetime.utcnow()
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Project).where(Project.is_active == True))
            projects = result.scalars().all()
        
        for project in projects:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(User).where(User.telegram_id == project.user_id))
                user = result.scalar_one_or_none()
                if not user:
                    continue
                
                if not user.is_admin:
                    has_access = False
                    if user.subscription_active and user.subscription_ends_at and user.subscription_ends_at > now:
                        has_access = True
                    elif user.trial_ends_at and user.trial_ends_at > now:
                        has_access = True
                    if not has_access:
                        continue
                
                interval = project.check_interval_minutes
                if not user.is_admin:
                    interval = max(interval, user.min_check_interval_minutes)
                
                last_check = self._last_check.get(project.id)
                if last_check:
                    elapsed = (now - last_check).total_seconds() / 60
                    if elapsed < interval:
                        continue
                
                self._last_check[project.id] = now
                
                task_key = f"project_{project.id}"
                if task_key not in self._tasks or self._tasks[task_key].done():
                    task = asyncio.create_task(self._process_project(project))
                    self._tasks[task_key] = task
                    logger.info(f"⏰ Project '{project.name}' (ID: {project.id}) scheduled")

    async def _download_media_with_retry(self, scraper, media_url: str, save_path: str, max_retries: int = 3) -> bool:
        for attempt in range(max_retries):
            if await scraper.download_media(media_url, save_path):
                try:
                    file_size = os.path.getsize(save_path)
                    if file_size < 1000:
                        logger.warning(f"Downloaded file too small: {file_size} bytes (attempt {attempt + 1})")
                        os.remove(save_path)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(3)
                            continue
                        return False
                    logger.info(f"✅ Media downloaded: {save_path} ({file_size} bytes)")
                    return True
                except Exception as e:
                    logger.warning(f"File check failed: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3)
                        continue
                    return False
            else:
                logger.warning(f"Download attempt {attempt + 1} failed for {media_url}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
        return False

    async def _get_last_scheduled_time(self, project_id: int) -> datetime:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PostQueue)
                .where(PostQueue.project_id == project_id, PostQueue.status == "pending")
                .order_by(PostQueue.scheduled_time.desc())
                .limit(1)
            )
            last_queued = result.scalar_one_or_none()
            if last_queued:
                return last_queued.scheduled_time
            return None

    async def _process_project(self, project: Project):
        logger.info(f"🔍 Processing project '{project.name}' (ID: {project.id})")
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.telegram_id == project.user_id))
            user = result.scalar_one_or_none()
            if not user:
                return
            
            if not user.is_admin:
                has_access = False
                now = datetime.utcnow()
                if user.subscription_active and user.subscription_ends_at and user.subscription_ends_at > now:
                    has_access = True
                elif user.trial_ends_at and user.trial_ends_at > now:
                    has_access = True
                if not has_access:
                    return
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SourceChannel).where(SourceChannel.project_id == project.id, SourceChannel.is_active == True)
            )
            sources = result.scalars().all()
            
            result = await session.execute(
                select(TargetChannel).where(TargetChannel.project_id == project.id, TargetChannel.is_active == True)
            )
            target = result.scalar_one_or_none()
        
        if not sources or not target:
            logger.warning(f"⚠️ Project '{project.name}' has no sources or target")
            return
        
        logger.info(f"📊 Project '{project.name}': {len(sources)} sources → {target.channel_title or '—'}")
        
        posts_to_publish = []
        total_parsed = 0
        
        async with TelegramScraper() as scraper:
            for source in sources:
                logger.info(f"📡 Fetching @{source.channel_username}")
                
                try:
                    posts = await scraper.get_posts(source.channel_username, limit=100)
                    logger.info(f"📨 @{source.channel_username}: {len(posts)} posts fetched")
                except Exception as e:
                    logger.error(f"❌ Failed to fetch @{source.channel_username}: {e}")
                    continue
                
                best_post = None
                best_score = -1
                
                for post in posts:
                    if await is_post_parsed(project.id, post["url"]):
                        continue
                    
                    if post.get("is_advertisement", False):
                        continue
                    
                    if source.max_age_hours and source.max_age_hours > 0:
                        if post.get("datetime"):
                            try:
                                post_time = datetime.fromisoformat(post["datetime"].replace("Z", "+00:00"))
                                age_hours = (datetime.utcnow() - post_time).total_seconds() / 3600
                                if age_hours > source.max_age_hours:
                                    logger.debug(f"⏭️ Post too old: {age_hours:.1f}h > {source.max_age_hours}h")
                                    continue
                            except:
                                pass
                    
                    if source.include_keywords:
                        keywords = [k.strip().lower() for k in source.include_keywords.split(",") if k.strip()]
                        post_text = post.get("text", "").lower()
                        if not any(keyword in post_text for keyword in keywords):
                            logger.debug(f"⏭️ No keywords in post from @{source.channel_username}")
                            continue
                    
                    media_type = post.get("media_type")
                    has_media = post.get("has_media", False)
                    
                    if source.media_filter == "photo_only":
                        if not has_media or media_type != "photo":
                            continue
                    elif source.media_filter == "video_only":
                        if not has_media or media_type != "video":
                            continue
                    
                    post["source_username"] = source.channel_username
                    post["source_title"] = source.channel_title
                    post["media_filter"] = source.media_filter
                    post["remove_original_text"] = source.remove_original_text
                    post["max_video_duration"] = source.max_video_duration
                    post["exclude_phrases"] = source.exclude_phrases
                    
                    post_time = datetime.utcnow()
                    if post.get("datetime"):
                        try:
                            post_time = datetime.fromisoformat(post["datetime"].replace("Z", "+00:00"))
                        except:
                            pass
                    
                    score, is_fallback = calculate_score(post, source.criteria, post_time)
                    
                    if is_fallback:
                        continue
                    
                    if score > best_score:
                        best_score = score
                        best_post = post
                
                if best_post:
                    if source.max_video_duration and source.max_video_duration > 0:
                        video_dur = best_post.get("video_duration", 0)
                        if video_dur > 0 and video_dur > source.max_video_duration:
                            logger.info(f"⏰ Video too long from @{source.channel_username}: {video_dur}s > {source.max_video_duration}s max")
                            continue
                    
                    media_type = best_post.get("media_type")
                    has_media = best_post.get("has_media", False)
                    
                    if source.media_filter == "photo_only":
                        if not has_media or media_type != "photo":
                            continue
                    elif source.media_filter == "video_only":
                        if not has_media or media_type != "video":
                            continue
                    
                    logger.info(f"🏆 Selected from @{source.channel_username}: score={best_score}, type={media_type}, duration={best_post.get('video_duration', 0)}s")
                    
                    await mark_post_parsed(project.id, source.id, best_post["url"])
                    total_parsed += 1
                    
                    media_downloaded = False
                    if best_post.get("has_media") and best_post.get("media_url"):
                        ext = "jpg" if best_post.get("media_type") == "photo" else "mp4"
                        filename = f"{uuid.uuid4()}.{ext}"
                        media_path = os.path.join(Config.TEMP_DIR, filename)
                        
                        if await self._download_media_with_retry(scraper, best_post["media_url"], media_path):
                            best_post["media_path"] = media_path
                            media_downloaded = True
                            logger.info(f"💾 Media saved: {media_path}")
                        else:
                            logger.warning(f"⚠️ Media download failed for @{source.channel_username}")
                    
                    if source.media_filter in ("photo_only", "video_only"):
                        if not media_downloaded:
                            logger.info(f"🚫 BLOCKED: media_filter={source.media_filter} but media download failed")
                            continue
                    
                    if source.remove_original_text and not media_downloaded:
                        logger.info(f"📝 Skipping (text removed, no media) from @{source.channel_username}")
                        continue
                    
                    has_text = bool(best_post.get("text", "").strip())
                    if not has_text and not media_downloaded:
                        logger.info(f"📭 Empty post from @{source.channel_username}, skipping")
                        continue
                    
                    posts_to_publish.append(best_post)
                    
                    async with AsyncSessionLocal() as session:
                        await session.execute(
                            update(SourceChannel)
                            .where(SourceChannel.id == source.id)
                            .values(last_parsed=datetime.utcnow(), last_post_url=best_post["url"])
                        )
                        await session.commit()
                else:
                    logger.info(f"😴 @{source.channel_username}: no suitable posts")
        
        if posts_to_publish:
            logger.info(f"📤 Found {len(posts_to_publish)} posts to queue")
            
            msk_now = get_moscow_time().replace(tzinfo=None)
            interval_minutes = max(project.post_interval_hours, user.min_post_interval_minutes)
            start_hour = project.active_hours_start
            end_hour = project.active_hours_end
            
            last_scheduled_utc = await self._get_last_scheduled_time(project.id)
            
            if last_scheduled_utc:
                last_scheduled_msk = last_scheduled_utc + timedelta(hours=3)
                next_time = last_scheduled_msk + timedelta(minutes=interval_minutes)
                
                if next_time <= msk_now:
                    minutes_since_start = (msk_now.hour - start_hour) * 60 + msk_now.minute
                    if minutes_since_start < 0:
                        next_time = msk_now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                    else:
                        slots = (minutes_since_start + interval_minutes - 1) // interval_minutes
                        next_time = msk_now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=slots * interval_minutes)
                
                if next_time.hour >= end_hour:
                    next_time = next_time.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
            else:
                minutes_since_start = (msk_now.hour - start_hour) * 60 + msk_now.minute
                if minutes_since_start < 0:
                    next_time = msk_now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                else:
                    slots = (minutes_since_start + interval_minutes - 1) // interval_minutes
                    next_time = msk_now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=slots * interval_minutes)
                
                if next_time.hour >= end_hour:
                    next_time = next_time.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
            
            for i, post in enumerate(posts_to_publish):
                if i > 0:
                    next_time = next_time + timedelta(minutes=interval_minutes)
                    if next_time.hour >= end_hour:
                        next_time = next_time.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
                
                utc_time = next_time - timedelta(hours=3)
                
                await self.poster.add_to_queue(
                    project_id=project.id,
                    target_channel_id=target.id,
                    post_data=post,
                    scheduled_time=utc_time,
                    platform=target.platform
                )
                logger.info(f"📅 Post {i+1} scheduled for {next_time.strftime('%d.%m.%Y %H:%M')} MSK")
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Project).where(Project.id == project.id))
                db_project = result.scalar_one()
                today = datetime.utcnow().date()
                if db_project.last_reset.date() < today:
                    db_project.posts_parsed_today = 0
                    db_project.posts_posted_today = 0
                    db_project.last_reset = datetime.utcnow()
                db_project.posts_parsed_today += total_parsed
                await session.commit()
        
        logger.info(f"✅ Project '{project.name}' processing completed")

    async def stop(self):
        self._running = False
        for task_key, task in self._tasks.items():
            if not task.done():
                task.cancel()
        logger.info("🔴 Scheduler stopped")