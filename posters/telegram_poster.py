import os
import logging
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from sqlalchemy import select, update
from database import AsyncSessionLocal
from models import PostQueue, PublishedPost, TargetChannel, Project
from utils import clean_caption
from config import Config

logger = logging.getLogger(__name__)


class TelegramPoster:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def add_to_queue(
        self, project_id: int, target_channel_id: int, 
        post_data: dict, scheduled_time: datetime, platform: str = "telegram"
    ):
        async with AsyncSessionLocal() as session:
            queue_item = PostQueue(
                project_id=project_id,
                target_channel_id=target_channel_id,
                platform=platform,
                post_data=post_data,
                scheduled_time=scheduled_time,
                status="pending"
            )
            session.add(queue_item)
            await session.commit()
            logger.info(f"📨 Post queued for project {project_id}")

    async def publish_post(self, queue_item: PostQueue) -> bool:
        real_chat_id = None
        signature = None
        
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TargetChannel).where(TargetChannel.id == queue_item.target_channel_id)
                )
                target = result.scalar_one_or_none()
                if not target:
                    await self._mark_failed(queue_item, "Целевой канал не найден")
                    return False
                
                if not target.channel_id:
                    await self._mark_failed(queue_item, "Chat ID не указан")
                    return False
                
                real_chat_id = target.channel_id
                
                result = await session.execute(
                    select(Project).where(Project.id == queue_item.project_id)
                )
                project = result.scalar_one_or_none()
                signature = project.signature if project else None
        except Exception as e:
            logger.error(f"Failed to get target info: {e}")
            await self._mark_failed(queue_item, "Ошибка получения данных канала")
            return False
        
        post_data = queue_item.post_data
        
        remove_text = post_data.get("remove_original_text", False)
        
        exclude_phrases_str = post_data.get("exclude_phrases", "")
        if exclude_phrases_str:
            exclude_phrases = [p.strip() for p in exclude_phrases_str.split(",") if p.strip()]
        else:
            exclude_phrases = None
        
        original_text = clean_caption(post_data.get("text", ""), exclude_phrases)
        
        if remove_text:
            caption = ""
        else:
            caption = original_text
        
        # Добавляем подпись проекта
        if signature:
            if caption:
                caption += f"\n\n{signature}"
            else:
                caption = signature
        
        # Источник если включено
        if Config.SHOW_SOURCE_SIGNATURE:
            source = post_data.get("source_username", "")
            if source:
                if caption:
                    caption += f"\n\n📡 @{source}"
                else:
                    caption = f"📡 @{source}"
        
        media_path = post_data.get("media_path")
        media_type = post_data.get("media_type")
        
        has_media = media_path and os.path.exists(media_path)
        has_original_text = bool(original_text.strip())
        
        # ЗАЩИТА: не публикуем если только подпись без медиа и без оригинального текста
        if not has_media and not has_original_text:
            await self._mark_failed(queue_item, "Нет медиа и нет текста — только подпись")
            return False
        
        # ПОВТОРНАЯ ПРОВЕРКА ФИЛЬТРА МЕДИА ПРИ ПУБЛИКАЦИИ
        media_filter = post_data.get("media_filter", "all")
        
        if media_filter == "photo_only":
            if not has_media or media_type != "photo":
                await self._mark_failed(queue_item, f"Фильтр: только фото, но медиа отсутствует или тип {media_type}")
                return False
        
        elif media_filter == "video_only":
            if not has_media or media_type != "video":
                await self._mark_failed(queue_item, f"Фильтр: только видео, но медиа отсутствует или тип {media_type}")
                return False
        
        html_tags = ["<a href=", "<b>", "<i>", "<code>", "<s>", "<u>", "<pre>", "<blockquote>"]
        parse_mode = None
        if caption and any(tag in caption for tag in html_tags):
            parse_mode = "HTML"
        
        if has_media:
            try:
                with open(media_path, "rb") as f:
                    if media_type == "photo":
                        await self.bot.send_photo(
                            chat_id=real_chat_id, photo=f,
                            caption=caption if caption else None,
                            parse_mode=parse_mode
                        )
                    elif media_type == "video":
                        await self.bot.send_video(
                            chat_id=real_chat_id, video=f,
                            caption=caption if caption else None,
                            parse_mode=parse_mode
                        )
                    else:
                        await self.bot.send_document(
                            chat_id=real_chat_id, document=f,
                            caption=caption if caption else None,
                            parse_mode=parse_mode
                        )
                
                try:
                    os.remove(media_path)
                except:
                    pass
                
                await self._mark_published(queue_item)
                logger.info(f"✅ Published post {queue_item.id} with media")
                return True
                
            except TelegramError as e:
                error_str = str(e).lower()
                logger.error(f"Failed to send media: {e}")
                
                # Fallback 1: пробуем без parse_mode
                if parse_mode and "parse" in error_str:
                    try:
                        with open(media_path, "rb") as f:
                            if media_type == "photo":
                                await self.bot.send_photo(
                                    chat_id=real_chat_id, photo=f, 
                                    caption=caption if caption else None
                                )
                            elif media_type == "video":
                                await self.bot.send_video(
                                    chat_id=real_chat_id, video=f, 
                                    caption=caption if caption else None
                                )
                            else:
                                await self.bot.send_document(
                                    chat_id=real_chat_id, document=f, 
                                    caption=caption if caption else None
                                )
                        try:
                            os.remove(media_path)
                        except:
                            pass
                        await self._mark_published(queue_item)
                        return True
                    except:
                        pass
                
                # === ИСПРАВЛЕНИЕ: не публикуем текст, если текст удалён ===
                if remove_text:
                    try:
                        os.remove(media_path)
                    except:
                        pass
                    error_text = str(e)[:80].replace("\n", " ")
                    await self._mark_failed(queue_item, f"Медиа не отправилось, текст удалён: {error_text}")
                    return False
                
                # Fallback 2: только текст (если текст не удалён)
                if caption:
                    try:
                        await self.bot.send_message(
                            chat_id=real_chat_id, text=caption, 
                            disable_web_page_preview=True
                        )
                        try:
                            os.remove(media_path)
                        except:
                            pass
                        await self._mark_published(queue_item)
                        return True
                    except:
                        pass
                
                error_text = str(e)[:80].replace("\n", " ")
                await self._mark_failed(queue_item, f"Ошибка отправки: {error_text}")
                return False
                
            except Exception as e:
                logger.error(f"Unexpected error sending media: {e}")
                
                # === ИСПРАВЛЕНИЕ: не публикуем текст, если текст удалён ===
                if remove_text:
                    try:
                        os.remove(media_path)
                    except:
                        pass
                    await self._mark_failed(queue_item, f"Медиа не отправилось, текст удалён")
                    return False
                
                # Fallback: только текст (если текст не удалён)
                if caption:
                    try:
                        await self.bot.send_message(
                            chat_id=real_chat_id, text=caption, 
                            disable_web_page_preview=True
                        )
                        try:
                            os.remove(media_path)
                        except:
                            pass
                        await self._mark_published(queue_item)
                        return True
                    except:
                        pass
                
                error_text = str(e)[:80].replace("\n", " ")
                await self._mark_failed(queue_item, f"Ошибка отправки: {error_text}")
                return False
        
        elif caption:
            try:
                await self.bot.send_message(
                    chat_id=real_chat_id, text=caption,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True
                )
                await self._mark_published(queue_item)
                return True
            except TelegramError as e:
                if parse_mode:
                    try:
                        await self.bot.send_message(
                            chat_id=real_chat_id, text=caption, 
                            disable_web_page_preview=True
                        )
                        await self._mark_published(queue_item)
                        return True
                    except:
                        pass
                error_text = str(e)[:80].replace("\n", " ")
                await self._mark_failed(queue_item, f"Ошибка отправки: {error_text}")
                return False
        
        await self._mark_failed(queue_item, "Пустой пост")
        return False

    async def _mark_published(self, queue_item: PostQueue):
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(PostQueue)
                .where(PostQueue.id == queue_item.id)
                .values(status="published", published_at=datetime.utcnow())
            )
            published = PublishedPost(
                project_id=queue_item.project_id,
                target_channel_id=queue_item.target_channel_id,
                source_channel_username=queue_item.post_data.get("source_username", ""),
                post_url=queue_item.post_data.get("url", ""),
                post_data=queue_item.post_data
            )
            session.add(published)
            await session.execute(
                update(TargetChannel)
                .where(TargetChannel.id == queue_item.target_channel_id)
                .values(last_posted=datetime.utcnow())
            )
            await session.commit()

    async def _mark_failed(self, queue_item: PostQueue, error_message: str):
        clean_error = error_message[:150].replace("\n", " ").strip()
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(PostQueue)
                .where(PostQueue.id == queue_item.id)
                .values(status="failed", error_message=clean_error)
            )
            await session.commit()
            logger.warning(f"❌ Post {queue_item.id} failed: {clean_error}")

    async def stop(self):
        logger.info("🔴 TelegramPoster stopped")