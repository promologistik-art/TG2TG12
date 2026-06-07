
Контент фабрика
1000 подписчиков
Отладка тг2тг
U2TG
Fix парсер бота
youtubebot
Telegram Search API Bot Guide
Content Factory
Дата через 120 дней
FoodTracker Bot
Отладка парсер бота
Сбор базы каналов для интеграций
Восстановление текста из кракозябр
Гибкий подход к лидогенерации мебели
Скрипт бота Евгений
Script for beginner technician bot
Спор с озоном
Оценка навыков разработчика ботов
Установка Claude на домашний ПК
Ведение журнала давления
Очистка липучки от клея
Очистка липучки шлифмашинки от клея
Search mp
парсинг бот
Обход блокировки VK API для постинга видео
Создание бота для автопостинга видео из Telegram в VK
КБЖУ 3 литров пива
Оплата выдачи заказов на ПВЗ Озон
Синонимы слова деньги
2DO бот
Приоритеты заработка на проектах
1000 фраз для приятного сна
Avatar creation prompt for three actresses
DeepSeek Model Identification
Создание бота для репоста видео из Telegram в VK
Подборка цитат из литературы мира
Письмо ИП без печати реквизиты
Песочное печенье с вареньем из муки и масла
Скрипт бота для парсинга и репоста постов
КБЖУ 3.1
ИП не платит НДС при ошибке в платеже
Замена роутера TP Link Archer C5
КБЖУ финал
YouTube Monetization Rules 2026
Создание бота для юнит экономики и ABC анализа
Монетизация навыков создания ботов
Декларация 1,2
Рецепт лепешки без дрожжей
Копирование ЭЦП с флешки на компьютер
Запекание форели в фольге
Как создать хостинг для бота
Монетизация ботов без бюджета
Сдача отчетности ИП на УСН через ЛК
Декларация
DeepSeek nutrition bot feasibility
КБЖУ куриных яиц
КБЖУ расчет завтрака
КБЖУ 2.0
кбжу 1.1.
Стоимость составления 3-НДФЛ в 2026
Создание бота для подсчета КБЖУ
Варианты обеда при диете стол 9
КБЖУ
Create Telegram Auto Comment Bot
Продвижение и релиз
Run Calorizator Parser Locally
Bot v7.3 improvements and next steps
20/03 комиссии
Create MPStats Telegram Bot
Уточнение запроса стол 9
Integrate commission calculation into bot
Integrate commission calculation into bot
Интеграция ботов для расчета комиссий
Создание сервиса липсинка
OpenClaw AI Assistant Guide
Настройка админки бота
бот для парсинга комиссий
Создание справочника комиссий для бота
Ошибка логики подстановки комиссий
Исправление ошибок админ панели бота
добавление расчета комиссии
7.2 кнопки и админка
Создание кнопок для чатбота
Иван Ефремов Лезвие бритвы
Расчет покупок и остатка
Редактирование и тестирование Python на GitHub
Создание ботов на Python в 3ds Max
Поиск функции создания шаблона Excel
7.1
Суммирование чисел из списка
Как запустить проект The Agency
Помощь с проектом agency agents
Помощь в исправлении ошибок бота
поисковик 5 0803
Корректировка бота SearchMP
Оценка экономического потенциала SearchMP
Решение проблемы объема товара
Анализ бота для поиска товаров на Ozon
Поисковик с оплатой на ип
Запрос информации о проекте
Контент фабрика
Вот исправленный блок удаления проекта. Замени в projects_callback эту часть:

python
elif data.startswith("confirm_delete_") and not data.startswith("confirm_delete_source"):
    project_id = int(data.replace("confirm_delete_", ""))
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SourceChannel).where(SourceChannel.project_id == project_id))
        await session.execute(delete(TargetChannel).where(TargetChannel.project_id == project_id))
        await session.execute(delete(PostQueue).where(PostQueue.project_id == project_id))
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.commit()
    if context.user_data.get(CURRENT_PROJECT_KEY) == project_id:
        context.user_data.pop(CURRENT_PROJECT_KEY, None)
    await query.edit_message_text("✅ Проект удалён")
Замени на:

python
elif data.startswith("confirm_delete_") and not data.startswith("confirm_delete_source"):
    project_id = int(data.replace("confirm_delete_", ""))
    async with AsyncSessionLocal() as session:
        from models import ParsedPost, PublishedPost
        await session.execute(delete(ParsedPost).where(ParsedPost.project_id == project_id))
        await session.execute(delete(PublishedPost).where(PublishedPost.project_id == project_id))
        await session.execute(delete(PostQueue).where(PostQueue.project_id == project_id))
        await session.execute(delete(SourceChannel).where(SourceChannel.project_id == project_id))
        await session.execute(delete(TargetChannel).where(TargetChannel.project_id == project_id))
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.commit()
    if context.user_data.get(CURRENT_PROJECT_KEY) == project_id:
        context.user_data.pop(CURRENT_PROJECT_KEY, None)
    await query.edit_message_text("✅ Проект удалён")
Добавилось удаление ParsedPost и PublishedPost перед удалением проекта. Та же правка нужна в TG2TG12 и U2TG.

полный
python
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, delete
from config import Config
from database import AsyncSessionLocal
from models import User, Project, SourceChannel, TargetChannel, PostQueue, ParsedPost, PublishedPost
from .utils import (
    get_current_project, get_sources_count, get_project_target,
    get_user_projects_count, check_user_access, check_action_limit
)
from .constants import CURRENT_PROJECT_KEY

logger = logging.getLogger(__name__)


async def my_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список проектов с кнопками-названиями."""
    telegram_id = update.effective_user.id
    has_access, message, user = await check_user_access(telegram_id)
    current_project = await get_current_project(telegram_id, context)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()
        result = await session.execute(select(Project).where(Project.user_id == telegram_id).order_by(Project.id))
        projects = result.scalars().all()
    
    if not projects:
        can_create, limit_msg = await check_action_limit(user, "create_project")
        keyboard = None
        if can_create or user.is_admin:
            keyboard = [[InlineKeyboardButton("➕ Создать проект", callback_data="create_project")]]
        
        text = "📭 У вас пока нет проектов.\n\nПроект — это связка из источников и целевого канала."
        if not can_create and not user.is_admin:
            text += f"\n\n{limit_msg}"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
        else:
            await update.message.reply_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
        return
    
    text = f"📁 <b>Ваши проекты</b> ({len(projects)} / {user.max_projects})\n\n"
    
    for p in projects:
        sources_count = await get_sources_count(p.id)
        target = await get_project_target(p.id)
        current_icon = "👉 " if current_project and p.id == current_project.id else ""
        target_name = target.channel_title if target else 'не задана'
        
        text += f"{current_icon}<b>{p.name}</b>\n"
        text += f"   📥 Источников: {sources_count}\n"
        text += f"   📤 Цель: {target_name}\n"
        text += f"   📊 Сегодня: {p.posts_parsed_today} / {p.posts_posted_today}\n\n"
    
    keyboard = []
    for p in projects:
        current_mark = "👉 " if current_project and p.id == current_project.id else ""
        keyboard.append([InlineKeyboardButton(
            f"{current_mark}{p.name}", callback_data=f"project_menu_{p.id}"
        )])
    
    can_create, _ = await check_action_limit(user, "create_project")
    if len(projects) < user.max_projects and (can_create or user.is_admin):
        keyboard.append([InlineKeyboardButton("➕ Создать новый проект", callback_data="create_project")])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )


async def project_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню конкретного проекта."""
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    
    project_id = int(query.data.replace("project_menu_", ""))
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id, Project.user_id == telegram_id)
        )
        project = result.scalar_one_or_none()
    
    if not project:
        await query.edit_message_text("❌ Проект не найден")
        return
    
    context.user_data[CURRENT_PROJECT_KEY] = project.id
    
    sources_count = await get_sources_count(project.id)
    target = await get_project_target(project.id)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PostQueue).where(PostQueue.project_id == project.id, PostQueue.status == "pending")
        )
        pending = len(result.scalars().all())
    
    target_name = target.channel_title if target else 'не задана'
    
    # post_interval_hours теперь хранит минуты
    if project.post_interval_hours < 60:
        interval_display = f"каждые {project.post_interval_hours} мин"
    else:
        hours = project.post_interval_hours // 60
        interval_display = f"каждые {hours} ч"
    
    text = (
        f"📁 <b>Проект «{project.name}»</b>\n\n"
        f"📥 Источников: {sources_count}\n"
        f"📤 Цель: {target_name}\n"
        f"⏰ Парсинг: каждые {project.check_interval_minutes} мин\n"
        f"📅 Постинг: {interval_display}\n"
        f"🕐 Активные часы: {project.active_hours_start}:00 – {project.active_hours_end}:00\n"
        f"📊 Сегодня: спарсено {project.posts_parsed_today} / опубликовано {project.posts_posted_today}\n"
        f"📬 В очереди: {pending}\n"
    )
    
    if project.signature:
        text += f"✍️ Подпись: {project.signature}\n"
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data=f"stats_project_{project.id}")],
        [InlineKeyboardButton("📥 Источники", callback_data=f"project_sources_{project.id}")],
        [InlineKeyboardButton("🎯 Сменить цель", callback_data=f"project_change_target_{project.id}")],
        [InlineKeyboardButton("⏰ Интервал парсинга", callback_data=f"project_set_check_{project.id}")],
        [InlineKeyboardButton("📅 Интервал постинга", callback_data=f"project_set_post_{project.id}")],
        [InlineKeyboardButton("✍️ Подпись", callback_data=f"project_set_signature_{project.id}")],
        [InlineKeyboardButton("❌ Удалить проект", callback_data=f"delete_project_{project.id}")],
        [InlineKeyboardButton("◀️ Назад к проектам", callback_data="back_to_projects")],
    ]
    
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )


async def projects_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback'ов управления проектами."""
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    data = query.data
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()
    
    if data == "create_project":
        can_create, limit_msg = await check_action_limit(user, "create_project")
        if not can_create and not user.is_admin:
            await query.edit_message_text(f"❌ {limit_msg}")
            return
        
        await _reset_all_dialogs(context)
        context.user_data['awaiting_project_name'] = True
        
        await query.edit_message_text("📁 Введите название нового проекта:\n/cancel — отмена")
        return
    
    if data.startswith("select_project_"):
        project_id = int(data.replace("select_project_", ""))
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Project).where(Project.id == project_id, Project.user_id == telegram_id)
            )
            project = result.scalar_one_or_none()
        if project:
            context.user_data[CURRENT_PROJECT_KEY] = project.id
            await query.edit_message_text(f"✅ Выбран проект «{project.name}»")
    
    elif data.startswith("project_sources_"):
        project_id = int(data.replace("project_sources_", ""))
        context.user_data[CURRENT_PROJECT_KEY] = project_id
        from .sources import my_sources
        await my_sources(update, context)
    
    elif data.startswith("project_change_target_"):
        project_id = int(data.replace("project_change_target_", ""))
        context.user_data[CURRENT_PROJECT_KEY] = project_id
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TargetChannel).where(TargetChannel.project_id == project_id)
            )
            old_target = result.scalar_one_or_none()
        
        if old_target:
            await session.execute(delete(TargetChannel).where(TargetChannel.id == old_target.id))
            await session.commit()
        
        await query.edit_message_text(
            "🎯 Старая цель удалена.\n\nИспользуйте /add_target чтобы добавить новую цель."
        )
    
    elif data.startswith("project_set_check_"):
        project_id = int(data.replace("project_set_check_", ""))
        context.user_data['temp_project_id'] = project_id
        from .settings import set_interval_start_callback
        await set_interval_start_callback(update, context)
    
    elif data.startswith("project_set_post_"):
        project_id = int(data.replace("project_set_post_", ""))
        context.user_data['temp_project_id'] = project_id
        from .settings import set_post_interval_start_callback
        await set_post_interval_start_callback(update, context)
    
    elif data.startswith("project_set_signature_"):
        project_id = int(data.replace("project_set_signature_", ""))
        context.user_data['temp_project_id'] = project_id
        from .settings import set_signature_start_callback
        await set_signature_start_callback(update, context)
    
    elif data.startswith("delete_project_"):
        project_id = int(data.replace("delete_project_", ""))
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{project_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")],
        ]
        await query.edit_message_text(
            "⚠️ Удалить проект? Все источники и настройки будут потеряны.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("confirm_delete_") and not data.startswith("confirm_delete_source"):
        project_id = int(data.replace("confirm_delete_", ""))
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ParsedPost).where(ParsedPost.project_id == project_id))
            await session.execute(delete(PublishedPost).where(PublishedPost.project_id == project_id))
            await session.execute(delete(PostQueue).where(PostQueue.project_id == project_id))
            await session.execute(delete(SourceChannel).where(SourceChannel.project_id == project_id))
            await session.execute(delete(TargetChannel).where(TargetChannel.project_id == project_id))
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.commit()
        if context.user_data.get(CURRENT_PROJECT_KEY) == project_id:
            context.user_data.pop(CURRENT_PROJECT_KEY, None)
        await query.edit_message_text("✅ Проект удалён")
    
    elif data == "cancel_delete":
        await query.edit_message_text("❌ Удаление отменено")
    
    elif data.startswith("stats_project_"):
        project_id = int(data.replace("stats_project_", ""))
        await show_project_stats(query, project_id)


async def _reset_all_dialogs(context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает все флаги активных диалогов."""
    keys_to_remove = [
        'temp_project_id', 'temp_post_interval', 'temp_media_filter',
        'temp_max_video_duration', 'temp_criteria', 'edit_source_id',
        'awaiting_criteria', 'awaiting_duration', 'awaiting_text_choice',
        'edit_views', 'edit_media_filter', 'temp_source', 'temp_project_name',
        'temp_criteria_views', 'temp_source_id', 'delete_source_id',
        'awaiting_broadcast', 'awaiting_project_name'
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    logger.info("Dialogs reset before project creation")


async def handle_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод названия нового проекта."""
    if not context.user_data.get('awaiting_project_name'):
        return
    
    await _reset_all_dialogs(context)
    context.user_data['awaiting_project_name'] = True
    
    name = update.message.text.strip()
    telegram_id = update.effective_user.id
    
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("❌ Название должно быть от 2 до 50 символов.")
        return
    
    has_access, access_msg, user = await check_user_access(telegram_id)
    if not has_access:
        await update.message.reply_text(access_msg)
        context.user_data['awaiting_project_name'] = False
        return
    
    can_create, limit_msg = await check_action_limit(user, "create_project")
    if not can_create and not user.is_admin:
        await update.message.reply_text(f"❌ {limit_msg}")
        context.user_data['awaiting_project_name'] = False
        return
    
    async with AsyncSessionLocal() as session:
        project = Project(
            user_id=telegram_id,
            name=name,
            check_interval_minutes=user.min_check_interval_minutes,
            post_interval_hours=max(user.min_post_interval_minutes, 60),
            active_hours_start=Config.DEFAULT_ACTIVE_HOURS_START,
            active_hours_end=Config.DEFAULT_ACTIVE_HOURS_END
        )
        session.add(project)
        await session.commit()
        context.user_data[CURRENT_PROJECT_KEY] = project.id
    
    context.user_data['awaiting_project_name'] = False
    
    await update.message.reply_text(
        f"✅ Проект «{name}» создан!\n\n"
        f"Теперь добавьте:\n"
        f"• /add_target — целевой канал\n"
        f"• /add_source — каналы-источники\n\n"
        f"💡 После добавления источников проект начнёт работу автоматически."
    )


async def show_project_stats(query, project_id: int):
    """Показывает статистику проекта."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()
    
    sources_count = await get_sources_count(project_id)
    target = await get_project_target(project_id)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PostQueue).where(PostQueue.project_id == project_id, PostQueue.status == "pending")
        )
        pending = len(result.scalars().all())
    
    target_name = target.channel_title if target else 'не задана'
    
    text = (
        f"📊 <b>Статистика «{project.name}»</b>\n\n"
        f"📥 Источников: {sources_count}\n"
        f"📤 Цель: {target_name}\n"
        f"⏰ Интервал парсинга: {project.check_interval_minutes} мин\n"
        f"📅 Интервал публикации: {project.post_interval_hours} мин\n"
        f"📈 Сегодня: спарсено {project.posts_parsed_today}, опубликовано {project.posts_posted_today}\n"
        f"📬 В очереди: {pending}"
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Назад к проекту", callback_data=f"project_menu_{project_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def back_to_projects_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к списку проектов."""
    query = update.callback_query
    await query.answer()
    await my_projects(update, context)


