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
        
        result = await session.execute(
            select(func.count()).select_from(Project).where(Project.user_id == user.id)
        )
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
    
    # Связь с KontentFabrik
    if context.args and context.args[0].startswith("kf_"):
        head_user_id = int(context.args[0].split("_")[1])
        from worker_reg import save_user_binding
        await save_user_binding(head_user_id, user.id)
        logger.info(f"🔗 User {user.id} bound to KontentFabrik user {head_user_id}")
    
    welcome = f"👋 Привет, {user.first_name or 'пользователь'}!\n\n"
    welcome += (
        "🤖 <b>TG2TG — парсинг и автопостинг</b>\n\n"
        "Я нахожу лучшие посты в Telegram-каналах и публикую их в ваш канал.\n\n"
    )
    
    if db_user.is_admin:
        welcome += "👑 <b>Режим администратора</b>\n\n"
    elif not has_project:
        welcome += (
            "🚀 <b>Быстрый старт:</b>\n"
            "1. /add_target — добавьте канал для публикации\n"
            "2. /add_source — добавьте канал-источник\n"
            "3. Готово! Бот начнёт парсить и постить автоматически\n\n"
        )
    
    welcome += (
        "📋 <b>Основные команды:</b>\n"
        "/my_projects — проекты\n"
        "/status — статистика\n"
        "/help — все команды\n\n"
        "🤖 Управляйте всеми ботами через @KontentFabrik_bot"
    )
    
    await update.message.reply_text(welcome, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    text = (
        "📚 <b>TG2TG — Справка</b>\n\n"
        "<b>📁 Проекты:</b>\n"
        "/my_projects — список ваших проектов\n\n"
        "<b>📥 Источники:</b>\n"
        "/add_source — добавить канал для парсинга\n"
        "/my_sources — список источников\n\n"
        "<b>📤 Целевые каналы:</b>\n"
        "/add_target — добавить канал для публикации\n"
        "/my_targets — список целевых каналов\n\n"
        "<b>⚙️ Настройки:</b>\n"
        "/set_interval — интервал проверки каналов\n"
        "/set_post_interval — интервал публикации\n"
        "/set_signature — подпись под постами\n\n"
        "<b>📊 Статистика и управление:</b>\n"
        "/status — общая статистика\n"
        "/project_stats — статистика по проекту\n"
        "/parse — запустить парсинг сейчас\n"
        "/queue — очередь публикации\n"
        "/postnow — опубликовать следующий пост\n"
        "/clear_failed — очистить неудавшиеся посты\n"
        "/reset_history — сбросить историю\n"
    )
    
    if await is_admin(user_id):
        text += (
            "\n<b>👑 Админ:</b>\n"
            "/admin — админ-панель\n"
            "/admin_set_tariff — установить тариф\n"
            "/admin_extend_trial — продлить триал\n"
            "/broadcast — рассылка\n"
            "/clear_queue — очистить очередь\n"
            "/clear_failed — очистить failed\n"
            "/clear_all — очистить всю очередь\n"
            "/clear_project — очистить очередь проекта\n"
        )
    
    text += (
        f"\n📲 <a href='https://t.me/{Config.ADMIN_USERNAME or 'admin'}'>Написать админу</a>"
        f"\n📢 <a href='https://t.me/+MAuGbcnBQmgxZTIy'>Больше ботов в канале</a>"
        f"\n🤖 <a href='https://t.me/KontentFabrik_bot'>KontentFabrik — головной бот</a>"
    )
    
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Действие отменено. Все диалоги сброшены.")
    return ConversationHandler.END