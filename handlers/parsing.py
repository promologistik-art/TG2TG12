import logging
from datetime import timedelta
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, delete
from database import AsyncSessionLocal, clear_parsed_cache
from models import Project, PostQueue, SourceChannel, ParsedPost
from utils import format_number
from .utils import require_project, get_sources_count, get_project_target, is_admin
from config import Config

logger = logging.getLogger(__name__)


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = None):
    """Безопасная отправка сообщения — работает и из команды, и из колбэка."""
    if update.callback_query:
        return await update.callback_query.message.reply_text(text, parse_mode=parse_mode)
    elif update.message:
        return await update.message.reply_text(text, parse_mode=parse_mode)
    else:
        return await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode=parse_mode)


async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    if not project:
        return
    
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ParsedPost).where(ParsedPost.project_id == project.id))
        await session.commit()
        await clear_parsed_cache()
    
    await _reply(update, context, f"✅ История для проекта «{project.name}» очищена.\nТеперь /parse найдёт все посты заново.")


async def parse_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    if not project:
        return
    
    target = await get_project_target(project.id)
    if not target:
        await _reply(update, context, "❌ Сначала добавьте целевой канал: /add_target")
        return
    
    sources_count = await get_sources_count(project.id)
    if sources_count == 0:
        await _reply(update, context, "❌ Сначала добавьте источники: /add_source")
        return
    
    msg = await _reply(update, context, f"🔄 Парсинг «{project.name}»...")
    
    scheduler = context.application.bot_data.get('scheduler')
    if scheduler:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Project).where(Project.id == project.id))
            old_project = result.scalar_one()
            old_parsed = old_project.posts_parsed_today
        
        await scheduler._process_project(project)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Project).where(Project.id == project.id))
            updated = result.scalar_one()
            new_parsed = updated.posts_parsed_today - old_parsed
        
        if new_parsed > 0:
            await msg.edit_text(
                f"✅ Парсинг завершён!\n\n"
                f"📊 Найдено новых постов: {new_parsed}\n"
                f"📊 Всего спарсено сегодня: {updated.posts_parsed_today}\n"
                f"📤 В очереди: /queue"
            )
        else:
            await msg.edit_text(
                f"✅ Парсинг завершён!\n\n"
                f"📊 Новых постов не найдено\n"
                f"📊 Всего спарсено сегодня: {updated.posts_parsed_today}\n\n"
                f"💡 Возможные причины:\n"
                f"• Все посты уже спарсены — /reset_history\n"
                f"• Посты не прошли критерии\n"
                f"• В каналах нет новых постов\n\n"
                f"/queue — проверить очередь"
            )
    else:
        await msg.edit_text("❌ Планировщик не найден")


async def queue_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    if not project:
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PostQueue).where(PostQueue.project_id == project.id).order_by(PostQueue.scheduled_time.desc()).limit(15)
        )
        items = result.scalars().all()
    
    if not items:
        await _reply(update, context, "📭 Очередь публикации пуста")
        return
    
    text = f"📬 <b>Очередь публикации «{project.name}»</b>\n\n"
    
    interval_minutes = int(project.post_interval_hours)
    if interval_minutes < 60:
        text += f"⏰ Интервал: каждые {interval_minutes} мин\n\n"
    else:
        hours = interval_minutes // 60
        text += f"⏰ Интервал: каждые {hours} ч\n\n"
    
    MSK_OFFSET = timedelta(hours=3)
    
    for item in items:
        post_data = item.post_data
        status_icon = {"pending": "⏳", "published": "✅", "failed": "❌"}.get(item.status, "❓")
        scheduled_msk = item.scheduled_time + MSK_OFFSET
        
        text += f"{status_icon} {scheduled_msk.strftime('%d.%m.%Y %H:%M')} МСК\n"
        text += f"   📡 {post_data.get('source_name', '?')}\n"
        text += f"   👁 {format_number(post_data.get('views', 0))} | ❤️ {format_number(post_data.get('likes', 0))}\n"
        
        if item.status == "failed" and item.error_message:
            text += f"   ⚠️ {item.error_message[:100]}\n"
        
        text += "\n"
    
    await _reply(update, context, text, parse_mode="HTML")


async def post_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительная публикация следующего поста из очереди (доступно всем пользователям)."""
    project = await require_project(update, context)
    if not project:
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PostQueue).where(PostQueue.project_id == project.id, PostQueue.status == "pending").order_by(PostQueue.scheduled_time).limit(1)
        )
        queue_item = result.scalar_one_or_none()
        
        if not queue_item:
            await _reply(update, context, "📭 Нет постов в очереди для публикации")
            return
        
        poster = context.application.bot_data.get('poster')
        if not poster:
            await _reply(update, context, "❌ Сервис публикации не найден")
            return
        
        msg = await _reply(update, context, "🚀 Публикую пост...")
        success = await poster.publish_post(queue_item)
        
        if success:
            result = await session.execute(select(Project).where(Project.id == project.id))
            db_project = result.scalar_one()
            db_project.posts_posted_today += 1
            await session.commit()
            
            post_data = queue_item.post_data
            await msg.edit_text(
                f"✅ Пост опубликован!\n\n"
                f"📡 {post_data.get('source_name', '?')}\n"
                f"👁 {format_number(post_data.get('views', 0))} | ❤️ {format_number(post_data.get('likes', 0))}"
            )
        else:
            error_msg = queue_item.error_message or 'неизвестная ошибка'
            await msg.edit_text(f"❌ Ошибка публикации: {error_msg}")


async def clear_old_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await _reply(update, context, "❌ Нет доступа")
        return
    
    msg = await _reply(update, context, "🧹 Очищаю pending посты...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PostQueue).where(PostQueue.status == "pending"))
        items = result.scalars().all()
        deleted = len(items)
        for item in items:
            await session.delete(item)
        await session.commit()
    await msg.edit_text(f"✅ Удалено {deleted} pending постов")


async def clear_failed_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистка failed постов (доступно всем пользователям)."""
    project = await require_project(update, context)
    if not project:
        return
    
    msg = await _reply(update, context, "🧹 Очищаю failed посты...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(PostQueue).where(
                PostQueue.project_id == project.id,
                PostQueue.status == "failed"
            )
        )
        await session.commit()
    await msg.edit_text("✅ Failed посты удалены")


async def clear_all_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await _reply(update, context, "❌ Нет доступа")
        return
    
    msg = await _reply(update, context, "🧹 Удаляю всю очередь...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PostQueue))
        items = result.scalars().all()
        deleted = len(items)
        for item in items:
            await session.delete(item)
        await session.commit()
    await msg.edit_text(f"✅ Удалено {deleted} постов из очереди")


async def clear_project_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    if not project:
        return
    
    msg = await _reply(update, context, f"🧹 Очищаю очередь проекта «{project.name}»...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PostQueue).where(PostQueue.project_id == project.id))
        items = result.scalars().all()
        deleted = len(items)
        for item in items:
            await session.delete(item)
        await session.commit()
    await msg.edit_text(f"✅ Удалено {deleted} постов из очереди проекта «{project.name}»")