#!/usr/bin/env python3
"""
Simpleparcer Bot
Version: 3.0.0 (30/05/26) — PostgreSQL + KontentFabrik
"""

import asyncio
import logging
import sys
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)

from config import Config
from database import init_db
from worker_reg import register_self
from handlers import (
    start, help_command, cancel,
    my_projects, projects_callback, project_menu_callback, handle_project_name,
    back_to_projects_callback,
    add_source_start, add_source_username, add_source_criteria,
    criteria_views_input, criteria_reactions_input,
    media_filter_callback, duration_callback, remove_text_callback,
    my_sources, edit_source_callback, delete_source_callback,
    confirm_delete_source_callback, cancel_delete_source_callback,
    edit_source_start, edit_views_input, edit_reactions_input,
    edit_media_filter_callback, edit_duration_callback, edit_remove_text_callback,
    edit_exclude_phrases_input, edit_keywords_input,
    add_keywords_yes_callback, add_keywords_skip_callback, process_keywords_input,
    back_to_sources_callback,
    add_target_start, add_target_forward, add_target_continue_callback,
    my_targets, delete_target_callback,
    set_interval_start, set_interval_callback,
    set_post_interval_start, set_post_interval_callback,
    set_post_start_time_callback,
    set_signature_start, set_signature_input,
    set_interval_start_callback, set_post_interval_start_callback,
    set_signature_start_callback,
    status, project_stats,
    parse_now, queue_status, post_now,
    clear_old_queue, clear_failed_queue, clear_all_queue, clear_project_queue,
    reset_history,
    admin_panel, admin_callback, admin_back_callback,
    admin_set_tariff_start, admin_extend_trial_start,
    broadcast_start, broadcast_send,
    test_scraper, debug_reactions,
    setup_bot_commands,
    AWAITING_SOURCE_USERNAME, AWAITING_TARGET_FORWARD, AWAITING_CRITERIA,
    AWAITING_INTERVAL, AWAITING_VIEWS, AWAITING_REACTIONS, AWAITING_SIGNATURE,
    AWAITING_POST_INTERVAL, AWAITING_POST_START_TIME,
    AWAITING_MEDIA_FILTER, AWAITING_REMOVE_TEXT,
    AWAITING_EDIT_VIEWS, AWAITING_EDIT_REACTIONS, AWAITING_EDIT_EXCLUDE_PHRASES,
    AWAITING_BROADCAST_MESSAGE, AWAITING_KEYWORDS, AWAITING_EDIT_KEYWORDS
)

from posters import TelegramPoster
from scheduler import Scheduler
from post_scheduler import PostScheduler
from backup import BackupService, AutoBackup
from cleanup import TempCleaner

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def safe_handle_project_name(update, context):
    if not context.user_data.get('awaiting_project_name'):
        return False
    return await handle_project_name(update, context)


async def safe_set_signature_input(update, context):
    if not context.user_data.get('temp_project_id'):
        return False
    if context.user_data.get('awaiting_project_name'):
        return False
    if context.user_data.get('awaiting_broadcast'):
        return False
    return await set_signature_input(update, context)


async def main():
    await init_db()
    logger.info("Database initialized")
    
    # === Регистрируем клона в общей таблице workers ===
    await register_self()
    
    app = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .build()
    )
    await setup_bot_commands(app)
    
    poster = TelegramPoster(app.bot)
    scheduler = Scheduler(poster)
    post_scheduler = PostScheduler(poster)
    
    app.bot_data['scheduler'] = scheduler
    app.bot_data['post_scheduler'] = post_scheduler
    app.bot_data['poster'] = poster
    
    scheduler_task = asyncio.create_task(scheduler.start())
    post_scheduler_task = asyncio.create_task(post_scheduler.start())
    
    backup_service = BackupService()
    auto_backup = AutoBackup(backup_service)
    auto_backup_task = asyncio.create_task(auto_backup.start())
    
    temp_cleaner = TempCleaner()
    temp_cleaner_task = asyncio.create_task(temp_cleaner.start())
    
    # ============ Command Handlers ============
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("test", test_scraper))
    app.add_handler(CommandHandler("debug_reactions", debug_reactions))
    app.add_handler(CommandHandler("my_projects", my_projects))
    app.add_handler(CommandHandler("my_sources", my_sources))
    app.add_handler(CommandHandler("my_targets", my_targets))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("project_stats", project_stats))
    app.add_handler(CommandHandler("parse", parse_now))
    app.add_handler(CommandHandler("queue", queue_status))
    app.add_handler(CommandHandler("postnow", post_now))
    app.add_handler(CommandHandler("clear_queue", clear_old_queue))
    app.add_handler(CommandHandler("clear_failed", clear_failed_queue))
    app.add_handler(CommandHandler("clear_all", clear_all_queue))
    app.add_handler(CommandHandler("clear_project", clear_project_queue))
    app.add_handler(CommandHandler("reset_history", reset_history))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("admin_set_tariff", admin_set_tariff_start))
    app.add_handler(CommandHandler("admin_extend_trial", admin_extend_trial_start))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # ============ CallbackQueryHandlers ============
    app.add_handler(CallbackQueryHandler(admin_back_callback, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(admin_|user_manage_|tariff_set_|user_tariff_|extend_user_|deactivate_user_|activate_user_|tariff_for_|set_tariff_|admin_set_tariff|admin_extend_trial|admin_deactivate|admin_activate)"))
    
    app.add_handler(CallbackQueryHandler(edit_source_callback, pattern="^edit_source_"))
    app.add_handler(CallbackQueryHandler(delete_source_callback, pattern="^del_source_"))
    app.add_handler(CallbackQueryHandler(confirm_delete_source_callback, pattern="^confirm_delete_source$"))
    app.add_handler(CallbackQueryHandler(cancel_delete_source_callback, pattern="^cancel_delete_source$"))
    app.add_handler(CallbackQueryHandler(back_to_sources_callback, pattern="^back_to_sources$"))
    
    app.add_handler(CallbackQueryHandler(delete_target_callback, pattern="^del_target_"))
    
    app.add_handler(CallbackQueryHandler(project_menu_callback, pattern="^project_menu_"))
    app.add_handler(CallbackQueryHandler(back_to_projects_callback, pattern="^back_to_projects$"))
    app.add_handler(CallbackQueryHandler(projects_callback, pattern="^(create_project|select_project_|delete_project_|confirm_delete_|cancel_delete|stats_project_|project_sources_|project_change_target_)"))
    
    # ============ ConversationHandlers ============
    add_source_conv = ConversationHandler(
        entry_points=[CommandHandler("add_source", add_source_start)],
        states={
            AWAITING_SOURCE_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_source_username),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_CRITERIA: [
                CallbackQueryHandler(add_source_criteria, pattern="^criteria_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_VIEWS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, criteria_views_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_REACTIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, criteria_reactions_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_MEDIA_FILTER: [
                CallbackQueryHandler(media_filter_callback, pattern="^media_"),
                CallbackQueryHandler(duration_callback, pattern="^duration_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_REMOVE_TEXT: [
                CallbackQueryHandler(remove_text_callback, pattern="^text_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_KEYWORDS: [
                CallbackQueryHandler(add_keywords_yes_callback, pattern="^add_keywords_yes$"),
                CallbackQueryHandler(add_keywords_skip_callback, pattern="^add_keywords_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_keywords_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    edit_source_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_source_start, pattern="^edit_(criteria|media|text|phrases|clear_phrases|keywords)_")],
        states={
            AWAITING_EDIT_VIEWS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_views_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_EDIT_REACTIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_reactions_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_MEDIA_FILTER: [
                CallbackQueryHandler(edit_media_filter_callback, pattern="^edit_media_"),
                CallbackQueryHandler(edit_duration_callback, pattern="^edit_duration_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_REMOVE_TEXT: [
                CallbackQueryHandler(edit_remove_text_callback, pattern="^edit_text_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_EDIT_EXCLUDE_PHRASES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_exclude_phrases_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_EDIT_KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_keywords_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    add_target_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_target", add_target_start),
            CallbackQueryHandler(add_target_continue_callback, pattern="^add_target_continue$")
        ],
        states={
            AWAITING_TARGET_FORWARD: [
                MessageHandler(filters.FORWARDED, add_target_forward),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    set_interval_conv = ConversationHandler(
        entry_points=[
            CommandHandler("set_interval", set_interval_start),
            CallbackQueryHandler(set_interval_start_callback, pattern="^project_set_check_")
        ],
        states={
            AWAITING_INTERVAL: [
                CallbackQueryHandler(set_interval_callback, pattern="^interval_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    set_post_interval_conv = ConversationHandler(
        entry_points=[
            CommandHandler("set_post_interval", set_post_interval_start),
            CallbackQueryHandler(set_post_interval_start_callback, pattern="^project_set_post_")
        ],
        states={
            AWAITING_POST_INTERVAL: [
                CallbackQueryHandler(set_post_interval_callback, pattern="^post_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
            AWAITING_POST_START_TIME: [
                CallbackQueryHandler(set_post_start_time_callback, pattern="^starttime_"),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    set_signature_conv = ConversationHandler(
        entry_points=[
            CommandHandler("set_signature", set_signature_start),
            CallbackQueryHandler(set_signature_start_callback, pattern="^project_set_signature_")
        ],
        states={
            AWAITING_SIGNATURE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, safe_set_signature_input),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            AWAITING_BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    
    app.add_handler(add_source_conv)
    app.add_handler(edit_source_conv)
    app.add_handler(add_target_conv)
    app.add_handler(set_interval_conv)
    app.add_handler(set_post_interval_conv)
    app.add_handler(set_signature_conv)
    app.add_handler(broadcast_conv)
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, safe_handle_project_name))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message", "callback_query"])
    
    logger.info(f"🟢 Bot started — Clone #{Config.CLONE_ID} (version 3.0.0)")
    
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        scheduler_task.cancel()
        post_scheduler_task.cancel()
        auto_backup_task.cancel()
        temp_cleaner_task.cancel()
        await scheduler.stop()
        await post_scheduler.stop()
        await auto_backup.stop()
        await temp_cleaner.stop()
        await poster.stop()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("🔴 Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)