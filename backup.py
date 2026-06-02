import os
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import text
from database import engine, AsyncSessionLocal
from config import Config

logger = logging.getLogger(__name__)


class BackupService:
    """Бэкап PostgreSQL через pg_dump в SQL-файл"""
    
    def __init__(self):
        self.backup_dir = Path(Config.BACKUP_DIR)
        self.max_backups = 7
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_backup(self) -> str:
        """Создать SQL-дамп базы данных."""
        date_str = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        backup_name = f"backup_{Config.TABLE_PREFIX}{date_str}.sql"
        backup_path = self.backup_dir / backup_name
        
        try:
            # Используем pg_dump через shell
            db_url = Config.DATABASE_URL
            # Извлекаем параметры из URL
            # postgresql://user:pass@host:port/dbname
            url_part = db_url.replace("postgresql://", "")
            user_pass, host_db = url_part.split("@")
            user, password = user_pass.split(":")
            host_port, dbname = host_db.split("/")
            host, port = host_port.split(":")
            
            env = os.environ.copy()
            env["PGPASSWORD"] = password
            
            cmd = [
                "pg_dump",
                "-h", host,
                "-p", port,
                "-U", user,
                "-d", dbname,
                "-f", str(backup_path),
                "--no-owner",
                "--no-acl"
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"✅ Backup created: {backup_name}")
                self._cleanup_old_backups()
                return str(backup_path)
            else:
                logger.error(f"pg_dump failed: {stderr.decode()}")
                return None
                
        except FileNotFoundError:
            # pg_dump не установлен — сохраняем текстовый лог
            logger.warning("pg_dump not found, creating text backup")
            return await self._create_text_backup(backup_path)
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return None
    
    async def _create_text_backup(self, backup_path: Path) -> str:
        """Создать текстовый бэкап (список таблиц и количество строк)"""
        try:
            async with AsyncSessionLocal() as session:
                # Список таблиц
                result = await session.execute(
                    text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
                )
                tables = [row[0] for row in result.fetchall()]
                
                with open(backup_path, "w") as f:
                    f.write(f"-- Backup created: {datetime.now()}\n\n")
                    for table in tables:
                        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = result.scalar()
                        f.write(f"-- {table}: {count} rows\n")
                
                logger.info(f"✅ Text backup created: {backup_path.name}")
                return str(backup_path)
        except Exception as e:
            logger.error(f"Text backup failed: {e}")
            return None
    
    def _cleanup_old_backups(self):
        """Удалить старые бэкапы."""
        try:
            backups = sorted(self.backup_dir.glob("backup_*"))
            if len(backups) > self.max_backups:
                for old in backups[:-self.max_backups]:
                    old.unlink()
                    logger.info(f"🗑️ Deleted old backup: {old.name}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    def list_backups(self) -> list:
        """Список бэкапов."""
        try:
            backups = sorted(self.backup_dir.glob("backup_*"), reverse=True)
            result = []
            for b in backups:
                stat = b.stat()
                result.append({
                    "name": b.name,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "created": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M")
                })
            return result
        except:
            return []


class AutoBackup:
    """Автоматический бэкап раз в сутки"""
    
    def __init__(self, backup_service: BackupService):
        self.backup_service = backup_service
        self._running = False
        self._task = None
    
    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._backup_loop())
        logger.info("🟢 AutoBackup started (daily at 03:00 MSK)")
    
    async def _backup_loop(self):
        from utils import get_moscow_time
        
        while self._running:
            try:
                now = get_moscow_time()
                target = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                
                wait = (target - now).total_seconds()
                await asyncio.sleep(min(wait, 3600))
                
                if self._running:
                    await self.backup_service.create_backup()
                    await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"AutoBackup error: {e}")
                await asyncio.sleep(3600)
    
    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("🔴 AutoBackup stopped")