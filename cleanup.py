import os
import asyncio
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


class TempCleaner:
    """Очистка временной папки от старых файлов."""
    
    def __init__(self, temp_dir: str = None, max_age_hours: int = 24):
        self.temp_dir = temp_dir or Config.TEMP_DIR
        self.max_age_hours = max_age_hours
        self._running = False
        self._task = None
    
    async def start(self):
        """Запустить авто-очистку."""
        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"🟢 TempCleaner started (cleaning files older than {self.max_age_hours} hours)")
    
    async def _cleanup_loop(self):
        """Цикл очистки (раз в 24 часа)."""
        while self._running:
            try:
                await self._cleanup()
                await asyncio.sleep(86400)  # 24 часа
            except Exception as e:
                logger.error(f"TempCleaner error: {e}")
                await asyncio.sleep(3600)
    
    async def _cleanup(self):
        """Очистка старых файлов."""
        if not os.path.exists(self.temp_dir):
            logger.warning(f"Temp directory not found: {self.temp_dir}")
            return
        
        now = datetime.utcnow()
        deleted_count = 0
        deleted_size = 0
        
        for filename in os.listdir(self.temp_dir):
            file_path = os.path.join(self.temp_dir, filename)
            if not os.path.isfile(file_path):
                continue
            
            try:
                file_mtime = datetime.utcfromtimestamp(os.path.getmtime(file_path))
                age_hours = (now - file_mtime).total_seconds() / 3600
                
                if age_hours > self.max_age_hours:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_count += 1
                    deleted_size += file_size
                    logger.debug(f"Deleted old file: {filename} (age: {age_hours:.1f} hours)")
            except Exception as e:
                logger.warning(f"Failed to delete {filename}: {e}")
        
        if deleted_count > 0:
            logger.info(f"🧹 TempCleaner: deleted {deleted_count} files ({deleted_size / 1024 / 1024:.2f} MB)")
    
    async def stop(self):
        """Остановить авто-очистку."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("🔴 TempCleaner stopped")