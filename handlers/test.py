import logging
import re
from telegram import Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup
from scrapers import TelegramScraper
from utils import format_number

logger = logging.getLogger(__name__)


async def test_scraper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ℹ️ /test [username]\nПример: /test durov")
        return
    
    raw = context.args[0]
    username = raw.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").replace("t.me/", "").strip("/")
    
    msg = await update.message.reply_text(f"🔍 Тестирую @{username}...")
    
    async with TelegramScraper() as scraper:
        info = await scraper.get_channel_info(username)
        if not info:
            await msg.edit_text(f"❌ Канал @{username} не найден")
            return
        
        posts = await scraper.get_posts(username, limit=5)
        
        if posts:
            text = f"📨 @{username}\nНайдено: {len(posts)}\n\n"
            for i, p in enumerate(posts[:5], 1):
                text += f"{i}. 👁 {format_number(p['views'])} | ❤️ {format_number(p['reactions'])}\n"
                text += f"   📎 {'📷' if p.get('media_type') == 'photo' else '🎬' if p.get('media_type') == 'video' else '📝'}\n"
                if p.get('text'):
                    text += f"   {p['text'][:50]}...\n"
                text += "\n"
        else:
            text = f"❌ Посты не найдены"
    
    await msg.edit_text(text)


async def debug_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ℹ️ /debug_reactions [username]")
        return
    
    username = context.args[0].replace("@", "").strip("/")
    msg = await update.message.reply_text(f"🔍 Анализирую реакции @{username}...")
    
    async with TelegramScraper() as scraper:
        url = f"https://t.me/s/{username}"
        html = await scraper._fetch(url)
        
        if not html:
            await msg.edit_text("❌ Не удалось загрузить страницу")
            return
        
        soup = BeautifulSoup(html, "lxml")
        messages = soup.find_all("div", class_="tgme_widget_message")[:3]
        
        if not messages:
            await msg.edit_text("❌ Сообщения не найдены")
            return
        
        # Отправляем результат в файле, чтобы избежать проблем с HTML
        result_lines = []
        for i, msg_div in enumerate(messages, 1):
            reactions_div = msg_div.find("div", class_="tgme_widget_message_reactions")
            
            result_lines.append(f"=== Пост {i} ===")
            
            if reactions_div:
                reactions_html = str(reactions_div)
                result_lines.append(f"Блок реакций: {reactions_html[:500]}")
                
                spans = reactions_div.find_all("span")
                for span in spans[:10]:
                    classes = span.get("class", [])
                    text = span.get_text(strip=True)
                    result_lines.append(f"  Span: classes={classes}, text='{text}'")
                
                reactions_text = reactions_div.get_text()
                emoji_pattern = r'([^\w\s\d]{1,3})\s*(\d{1,6})'
                matches = re.findall(emoji_pattern, reactions_text)
                if matches:
                    result_lines.append(f"  Эмодзи+числа: {matches}")
            else:
                result_lines.append(f"Блок реакций НЕ НАЙДЕН")
                result_lines.append(f"HTML сообщения: {str(msg_div)[:300]}")
            
            result_lines.append("")
        
        full_result = "\n".join(result_lines)
        
        # Отправляем как файл
        from io import BytesIO
        result_file = BytesIO(full_result.encode('utf-8'))
        result_file.name = f"reactions_{username}.txt"
        
        await msg.delete()
        await update.message.reply_document(
            document=result_file,
            filename=f"reactions_{username}.txt",
            caption=f"🔍 Результат анализа @{username}"
        )