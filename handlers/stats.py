import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from database import AsyncSessionLocal
from models import User, Project, PostQueue, SourceChannel
from .utils import require_project, get_sources_count, get_project_target, TARIFF_LIMITS, is_admin

logger = logging.getLogger(__name__)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    
    # Проверяем, админ ли пользователь
    admin = await is_admin(telegram_id)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()
        
        result = await session.execute(select(Project).where(Project.user_id == telegram_id))
        projects = result.scalars().all()
        
        total_parsed = sum(p.posts_parsed_today for p in projects)
        total_posted = sum(p.posts_posted_today for p in projects)
        
        total_sources = 0
        for p in projects:
            sources_count = await get_sources_count(p.id)
            total_sources += sources_count
    
    tariff_name = TARIFF_LIMITS.get(user.tariff, {}).get('name', user.tariff)
    
    text = f"📊 <b>Ваша статистика</b>\n\n"
    text += f"💎 <b>Тариф:</b> {tariff_name}\n"
    
    # Для админа показываем особый статус
    if admin:
        text += f"👑 <b>Статус:</b> Администратор (без ограничений)\n"
    else:
        # Для обычных пользователей проверяем подписку/триал
        if user.subscription_active and user.subscription_ends_at and user.subscription_ends_at > datetime.utcnow():
            ends_at = user.subscription_ends_at
            days_left = (ends_at - datetime.utcnow()).days
            text += f"📅 Подписка до: {ends_at.strftime('%d.%m.%Y')} ({days_left} дн.)\n"
        elif user.trial_ends_at and user.trial_ends_at > datetime.utcnow():
            ends_at = user.trial_ends_at
            days_left = (ends_at - datetime.utcnow()).days
            text += f"🎁 Триал до: {ends_at.strftime('%d.%m.%Y')} ({days_left} дн.)\n"
        else:
            text += f"⚠️ Доступ приостановлен\n"
    
    text += f"\n📊 <b>Ваши лимиты:</b>\n"
    text += f"• Макс. проектов: {user.max_projects}\n"
    text += f"• Макс. источников на проект: {user.max_sources_per_project}\n"
    text += f"• Мин. интервал постинга: {user.min_post_interval_minutes} мин\n"
    text += f"• Мин. интервал парсинга: {user.min_check_interval_minutes} мин\n"
    
    text += f"\n📈 <b>Текущее использование:</b>\n"
    text += f"• Проектов: {len(projects)} / {user.max_projects}\n"
    text += f"• Всего источников: {total_sources}\n"
    
    text += f"\n📅 <b>За сегодня:</b>\n"
    text += f"• Спарсено: {total_parsed}\n"
    text += f"• Опубликовано: {total_posted}\n"
    
    text += f"\n/my_projects — статистика по проектам"
    
    await update.message.reply_text(text, parse_mode="HTML")


async def project_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    
    if not project:
        return
    
    sources_count = await get_sources_count(project.id)
    target = await get_project_target(project.id)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PostQueue).where(PostQueue.project_id == project.id, PostQueue.status == "pending")
        )
        pending = len(result.scalars().all())
    
    text = (
        f"📊 <b>Статистика «{project.name}»</b>\n\n"
        f"📥 Источников: {sources_count}\n"
        f"📤 Цель: {target.channel_title if target else 'не задан'}\n"
        f"⏰ Интервал: {project.check_interval_minutes} мин\n"
        f"📈 Сегодня: {project.posts_parsed_today} / {project.posts_posted_today}\n"
        f"📬 В очереди: {pending}"
    )
    
    await update.message.reply_text(text, parse_mode="HTML")