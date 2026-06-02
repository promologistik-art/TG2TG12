import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import select, func
from config import Config
from database import AsyncSessionLocal
from models import User, Project
from .utils import is_admin, check_user_access, TARIFF_LIMITS

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    
    user = update.effective_user
    is_new_user = False
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            is_new_user = True
            db_user = User(
                telegram_id=user.id, username=user.username, full_name=user.full_name,
                is_admin=(user.id == Config.ADMIN_ID),
                max_projects=Config.DEFAULT_MAX_PROJECTS,
                max_sources_per_project=Config.DEFAULT_MAX_SOURCES_PER_PROJECT
            )
            if user.id == Config.ADMIN_ID:
                db_user.is_admin = True
                db_user.tariff = "unlimited"
                db_user.subscription_active = True
                db_user.max_projects = 999
                db_user.max_sources_per_project = 999
                db_user.min_post_interval_minutes = 1
                db_user.min_check_interval_minutes = 5
                db_user.trial_ends_at = datetime.utcnow() + timedelta(days=36500)
            session.add(db_user)
            await session.commit()
        else:
            db_user.username = user.username
            db_user.full_name = user.full_name
            if user.id == Config.ADMIN_ID:
                db_user.is_admin = True
                db_user.tariff = "unlimited"
                db_user.subscription_active = True
                db_user.max_projects = 999
                db_user.max_sources_per_project = 999
            await session.commit()
        
        result = await session.execute(select(func.count()).select_from(Project).where(Project.user_id == user.id))
        has_project = result.scalar() > 0
    
    if is_new_user and user.id != Config.ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=Config.ADMIN_ID,
                text=f"🆕 <b>Новый пользователь!</b>\n👤 {user.full_name or '—'}\n📝 @{user.username or 'нет'}\n🆔 {user.id}",
                parse_mode="HTML"
            )
        except:
            pass
    
    welcome = f"👋 Привет, {user.first_name or 'пользователь'}!\n\n"
    welcome += "Я бот для автоматического парсинга и публикации постов из Telegram-каналов.\n\n"
    
    if db_user.is_admin:
        welcome += "👑 <b>Режим администратора</b>\n\n"
    elif not has_project:
        welcome += "🚀 Для начала работы создайте проект: /my_projects\n\n"
    
    welcome += (
        "📋 Основные команды:\n"
        "/my_projects — мои проекты\n"
        "/add_source — добавить источник\n"
        "/add_target — добавить целевой канал\n"
        "/status — статистика\n"
        "/help — все команды"
    )
    
    await update.message.reply_text(welcome, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    text = (
        "📚 <b>Справка по командам</b>\n\n"
        "<b>Проекты:</b>\n"
        "/my_projects - список ваших проектов\n\n"
        "<b>Источники:</b>\n"
        "/add_source - добавить канал для парсинга\n"
        "/my_sources - список источников\n\n"
        "<b>Целевые каналы:</b>\n"
        "/add_target - добавить канал для публикации\n"
        "/my_targets - список целевых каналов\n\n"
        "<b>Настройки:</b>\n"
        "/set_interval - интервал парсинга\n"
        "/set_post_interval - интервал публикации\n"
        "/set_signature - подпись под постами\n\n"
        "<b>Управление:</b>\n"
        "/status - общая статистика\n"
        "/project_stats - статистика по проекту\n"
        "/parse - запустить парсинг сейчас\n"
        "/queue - очередь публикации\n"
        "/postnow - опубликовать следующий пост немедленно\n"
        "/reset_history - сбросить историю спарсенных постов\n"
    )
    
    if await is_admin(user_id):
        text += (
            "\n<b>Админские команды:</b>\n"
            "/admin — админ-панель\n"
            "/admin_set_tariff — установить тариф\n"
            "/admin_extend_trial — продлить триал\n"
            "/broadcast — рассылка\n"
            "/clear_queue — очистить очередь\n"
            "/clear_failed — очистить failed\n"
            "/clear_all — очистить всю очередь\n"
            "/clear_project — очистить очередь проекта\n"
        )
    else:
        text += (
            "\n<b>💎 Тарифы:</b>\n"
            "• Базовый — 290 ₽/мес (1 проект, 3 источника, постинг от 2ч)\n"
            "• Стандарт — 590 ₽/мес (3 проекта, 5 источников, постинг от 1ч)\n"
            "• PRO — 990 ₽/мес (10 проектов, 10 источников, постинг от 30мин)\n"
        )
    
    admin_username = Config.ADMIN_USERNAME or "admin"
    text += f"\n\n📲 <a href='https://t.me/{admin_username}'>Написать админу</a>"
    text += "\n\n📢 <a href='https://t.me/+MAuGbcnBQmgxZTIy'>Больше наших ботов в канале</a>"
    
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Действие отменено")
    return ConversationHandler.END