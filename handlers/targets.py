import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import select, delete
from database import AsyncSessionLocal
from models import TargetChannel, Project
from .utils import require_project, get_sources_count, get_project_target, send_project_ready_message
from .constants import AWAITING_TARGET_FORWARD, CURRENT_PROJECT_KEY

logger = logging.getLogger(__name__)


async def add_target_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление целевого канала. Проверяет текущий проект и другие проекты."""
    # Сохраняем текущий проект перед очисткой
    current_project = context.user_data.get(CURRENT_PROJECT_KEY)
    context.user_data.clear()
    if current_project:
        context.user_data[CURRENT_PROJECT_KEY] = current_project
    
    telegram_id = update.effective_user.id
    
    project = await require_project(update, context)
    if not project:
        return ConversationHandler.END
    
    # Проверяем, есть ли target в ТЕКУЩЕМ проекте
    target = await get_project_target(project.id)
    if target:
        await update.message.reply_text(
            f"⚠️ В текущем проекте «{project.name}» уже есть целевой канал:\n"
            f"📤 {target.channel_title}\n\n"
            f"Чтобы добавить новый, сначала удалите текущий через /my_targets\n"
            f"Или переключитесь на другой проект в /my_projects"
        )
        return ConversationHandler.END
    
    # Проверяем, есть ли target в ДРУГИХ проектах пользователя
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Project).where(
                Project.user_id == telegram_id,
                Project.id != project.id,
                Project.is_active == True
            )
        )
        other_projects = result.scalars().all()
    
    other_with_target = []
    for p in other_projects:
        t = await get_project_target(p.id)
        if t:
            other_with_target.append((p, t))
    
    if other_with_target:
        text = f"📁 Текущий проект: «{project.name}»\n\n"
        text += "ℹ️ Целевой канал уже существует в других проектах:\n"
        for p, t in other_with_target:
            text += f"• Проект «{p.name}» → {t.channel_title}\n"
        text += f"\nДобавляем новый целевой канал в проект «{project.name}». Продолжить?"
        
        keyboard = []
        for p, t in other_with_target:
            keyboard.append([InlineKeyboardButton(
                f"🔄 Переключиться на «{p.name}»", 
                callback_data=f"select_project_{p.id}"
            )])
        keyboard.append([InlineKeyboardButton(
            f"✅ Да, добавить в «{project.name}»", 
            callback_data="add_target_continue"
        )])
        
        await update.message.reply_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END
    
    # Всё чисто — продолжаем
    context.user_data['temp_project_id'] = project.id
    context.user_data['temp_project_name'] = project.name
    
    me = await context.bot.get_me()
    await update.message.reply_text(
        f"📤 Добавление целевого канала в «{project.name}»\n\n"
        f"1. Добавьте @{me.username} в администраторы канала\n"
        f"2. Выдайте боту права на публикацию сообщений\n"
        f"3. Перешлите сюда любое сообщение из этого канала\n\n"
        f"⚠️ Пересылать нужно именно из канала, не из избранного."
    )
    return AWAITING_TARGET_FORWARD


async def add_target_continue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для продолжения добавления target после предупреждения о других проектах."""
    query = update.callback_query
    await query.answer()
    
    project = await require_project(update, context)
    if not project:
        return ConversationHandler.END
    
    target = await get_project_target(project.id)
    if target:
        await query.edit_message_text(
            f"⚠️ В проекте «{project.name}» уже есть целевой канал: {target.channel_title}\n"
            f"Удалите его через /my_targets"
        )
        return ConversationHandler.END
    
    context.user_data['temp_project_id'] = project.id
    context.user_data['temp_project_name'] = project.name
    
    me = await context.bot.get_me()
    await query.edit_message_text(
        f"📤 Добавление целевого канала в «{project.name}»\n\n"
        f"1. Добавьте @{me.username} в администраторы канала\n"
        f"2. Выдайте боту права на публикацию сообщений\n"
        f"3. Перешлите сюда любое сообщение из этого канала\n\n"
        f"⚠️ Пересылать нужно именно из канала, не из избранного."
    )
    return AWAITING_TARGET_FORWARD


async def add_target_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    
    if not msg.forward_from_chat or msg.forward_from_chat.type != 'channel':
        await update.message.reply_text("❌ Перешлите сообщение из канала.")
        return AWAITING_TARGET_FORWARD
    
    chat = msg.forward_from_chat
    project_id = context.user_data.get('temp_project_id')
    project_name = context.user_data.get('temp_project_name')
    
    try:
        test_msg = await context.bot.send_message(chat.id, "🔧 Проверка прав...")
        await test_msg.delete()
    except:
        await update.message.reply_text("❌ Бот не имеет прав администратора.")
        return AWAITING_TARGET_FORWARD
    
    async with AsyncSessionLocal() as session:
        channel = TargetChannel(
            project_id=project_id,
            platform="telegram",
            channel_id=chat.id,
            channel_username=chat.username,
            channel_title=chat.title
        )
        session.add(channel)
        await session.commit()
    
    await update.message.reply_text(
        f"✅ Канал «{chat.title}» добавлен!\n\n"
        f"Теперь добавьте источники: /add_source"
    )
    
    for key in ['temp_project_id', 'temp_project_name']:
        context.user_data.pop(key, None)
    
    sources_count = await get_sources_count(project_id)
    if sources_count > 0:
        await send_project_ready_message(update, project_name)
    
    return ConversationHandler.END


async def my_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    if not project:
        return
    
    target = await get_project_target(project.id)
    if not target:
        await update.message.reply_text(
            f"📭 В проекте «{project.name}» нет целевого канала.\n"
            f"Добавьте: /add_target"
        )
        return
    
    text = f"🎯 <b>Целевой канал «{project.name}»</b>\n\n"
    text += f"📝 {target.channel_title}\n"
    if target.channel_username:
        text += f"🔗 @{target.channel_username}\n"
    text += f"🆔 {target.channel_id}\n"
    
    keyboard = [[InlineKeyboardButton("❌ Удалить", callback_data=f"del_target_{target.id}")]]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def delete_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.replace("del_target_", ""))
    
    async with AsyncSessionLocal() as session:
        await session.execute(delete(TargetChannel).where(TargetChannel.id == target_id))
        await session.commit()
    
    await query.edit_message_text("✅ Целевой канал удалён")