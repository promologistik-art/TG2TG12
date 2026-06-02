"""Регистрация клона в общей таблице workers + привязки пользователей"""
import logging
from datetime import datetime
from database import AsyncSessionLocal
from models import Worker, UserBinding
from config import Config

logger = logging.getLogger(__name__)


async def register_self():
    """Регистрирует этого клона в общей таблице workers"""
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        
        result = await session.execute(
            select(Worker).where(
                Worker.bot_type == Config.BOT_TYPE,
                Worker.clone_id == Config.CLONE_ID
            )
        )
        worker = result.scalar_one_or_none()
        
        if not worker:
            worker = Worker(
                bot_type=Config.BOT_TYPE,
                clone_id=Config.CLONE_ID,
                bot_username=Config.BOT_USERNAME,
                db_prefix=Config.TABLE_PREFIX,
                updated_at=datetime.utcnow()
            )
            session.add(worker)
        else:
            worker.bot_username = Config.BOT_USERNAME
            worker.db_prefix = Config.TABLE_PREFIX
            worker.is_active = True
            worker.updated_at = datetime.utcnow()
        
        await session.commit()
        logger.info(f"✅ Registered worker: {Config.BOT_TYPE}#{Config.CLONE_ID}")


async def save_user_binding(head_user_id: int, worker_user_id: int):
    """Сохраняет привязку: head_user → worker_user"""
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        
        result = await session.execute(
            select(UserBinding).where(
                UserBinding.head_user_id == head_user_id,
                UserBinding.bot_type == Config.BOT_TYPE
            )
        )
        binding = result.scalar_one_or_none()
        
        if not binding:
            binding = UserBinding(
                head_user_id=head_user_id,
                worker_user_id=worker_user_id,
                bot_type=Config.BOT_TYPE,
                clone_id=Config.CLONE_ID
            )
            session.add(binding)
        else:
            binding.worker_user_id = worker_user_id
            binding.clone_id = Config.CLONE_ID
        
        await session.commit()
        logger.info(f"✅ Binding saved: head={head_user_id} → clone {Config.CLONE_ID}")