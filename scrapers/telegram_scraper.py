import aiohttp
import asyncio
import re
import logging
import json
from typing import Optional, List, Dict
from bs4 import BeautifulSoup
from config import Config
from utils import parse_number

logger = logging.getLogger(__name__)

AD_KEYWORDS = [
    '#реклама', '#спонсор', '#партнер', '#партнёр', '#ad', '#рекламныйпост',
    'реклама', 'спонсор', 'партнёрский', 'промо', 'сообщение от партнёра',
    'на правах рекламы', 'платное размещение', 'спонсируется', 'advertisement',
    '#sponsored', '#promo', '#sponsor',
    'сбер', 'сбербанк', 'sber', 'sberbank',
    'альфа-банк', 'альфа банк', 'alfabank',
    'втб', 'vtb',
    'тинькофф', 'тиньков', 'tinkoff',
    'мтс', 'mts',
    'билайн', 'beeline',
    'мегафон', 'megafon',
    'газпромбанк', 'россельхозбанк', 'рсхб',
    'отп банк', 'otpbank',
    'совкомбанк', 'sovcombank',
    'райффайзен', 'raiffeisen',
    'почта банк', 'почтабанк',
    'хоум кредит', 'home credit',
    'ренессанс кредит', 'rencredit',
    'юникредит', 'unicredit',
    'промсвязьбанк', 'псб',
    'ак барс', 'акбарс',
    'уралсиб', 'uralsib',
    'зенит банк', 'zenitbank',
    'мкб', 'московский кредитный банк',
    'росбанк', 'rosbank',
    'ситибанк', 'citibank',
    'теле2', 'tele2',
    'yota', 'йота',
    'ростелеком', 'rostelecom',
    'дом.ру', 'domru',
    'wildberries', 'вайлдберриз', 'вб',
    'ozon', 'озон',
    'яндекс маркет', 'yandex market',
    'алиэкспресс', 'aliexpress',
    'сбермегамаркет', 'мегамаркет',
    'кредитная карта', 'кредит наличными',
    'дебетовая карта', 'оформить карту',
    'рефинансирование', 'ипотека',
    'микрозайм', 'займ до зарплаты',
    'вклад под', 'накопительный счет',
    'инвестиции в', 'брокерский счет',
    'страхование жизни', 'осаго', 'каско',
    'узнать подробнее на сайте',
    'перейти на сайт',
    'жми на ссылку',
    'только сегодня', 'ограниченное предложение',
    'скидка до', 'распродажа',
    'купить со скидкой',
    'получите бесплатно',
    'пройдите опрос', 'заполните анкету',
]


class TelegramScraper:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        headers = {
            "User-Agent": Config.SCRAPER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        self.session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def _fetch(self, url: str) -> Optional[str]:
        for attempt in range(Config.SCRAPER_RETRIES):
            try:
                async with self.session.get(url, timeout=Config.SCRAPER_TIMEOUT) as resp:
                    if resp.status == 200:
                        return await resp.text()
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                await asyncio.sleep(2)
        return None

    async def get_channel_info(self, username: str) -> Optional[Dict]:
        url = f"https://t.me/{username}"
        html = await self._fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("meta", property="og:title")
        title = title_tag["content"] if title_tag else username
        title = title.replace("Telegram: Contact @", "").strip()
        return {"username": username, "title": title}

    async def get_posts(self, username: str, limit: int = 10) -> List[Dict]:
        url = f"https://t.me/s/{username}"
        html = await self._fetch(url)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        posts = []
        for msg_div in soup.find_all("div", class_="tgme_widget_message")[:limit]:
            try:
                post = self._parse_message(msg_div, username)
                if post:
                    if self._is_advertisement(post):
                        logger.debug(f"Skipping ad: {post.get('url', '')}")
                        continue
                    posts.append(post)
            except Exception as e:
                logger.error(f"Parse error: {e}")
        posts.sort(key=lambda x: x.get("datetime", ""), reverse=True)
        return posts

    def _is_advertisement(self, post: Dict) -> bool:
        text = post.get("text", "").lower()
        for keyword in AD_KEYWORDS:
            if keyword.lower() in text:
                return True
        return False

    def _is_forwarded(self, msg_div) -> bool:
        forwarded = msg_div.find("div", class_="tgme_widget_message_forwarded")
        if forwarded:
            return True
        if msg_div.get("data-forward"):
            return True
        return False

    def _parse_message(self, msg_div, username: str) -> Optional[Dict]:
        data_post = msg_div.get("data-post")
        if not data_post:
            return None
        parts = data_post.split("/")
        if len(parts) < 2:
            return None
        message_id = parts[1]
        post_url = f"https://t.me/{username}/{message_id}"
        
        post_datetime = ""
        time_tag = msg_div.find("time")
        if time_tag and time_tag.has_attr("datetime"):
            post_datetime = time_tag["datetime"]
        
        text_div = msg_div.find("div", class_="tgme_widget_message_text")
        text = text_div.get_text(strip=False) if text_div else ""
        
        views = 0
        views_span = msg_div.find("span", class_="tgme_widget_message_views")
        if views_span:
            views = parse_number(views_span.get_text(strip=True))
        
        reactions = self._parse_reactions(msg_div)
        is_forwarded = self._is_forwarded(msg_div)
        
        has_photo = False
        has_video = False
        media_url = None
        media_type = None
        video_duration = 0
        
        photo_wrap = msg_div.find("a", class_="tgme_widget_message_photo_wrap")
        if photo_wrap:
            has_photo = True
            media_type = "photo"
            img = photo_wrap.find("img")
            if img:
                media_url = img.get("src")
            if not media_url:
                style = photo_wrap.get("style", "")
                bg_match = re.search(r"url\('(.+?)'\)", style)
                if bg_match:
                    media_url = bg_match.group(1)
        
        if not has_photo:
            gallery = msg_div.find("div", class_="tgme_widget_message_album_wrap")
            if gallery:
                first_photo = gallery.find("a", class_="tgme_widget_message_photo_wrap")
                if first_photo:
                    has_photo = True
                    media_type = "photo"
                    img = first_photo.find("img")
                    if img:
                        media_url = img.get("src")
        
        if not has_photo:
            video = msg_div.find("video")
            if video:
                src = video.get("src", "")
                if src and ("file/" in src or "video/" in src):
                    has_video = True
                    media_type = "video"
                    media_url = src
                    duration_attr = video.get("duration", "0")
                    try:
                        video_duration = int(float(duration_attr))
                    except:
                        video_duration = 0
        
        if not has_photo and not has_video:
            round_video = msg_div.find("video", class_="tgme_widget_message_roundvideo")
            if round_video:
                src = round_video.get("src", "")
                if src:
                    has_video = True
                    media_type = "video"
                    media_url = src
                    duration_attr = round_video.get("duration", "0")
                    try:
                        video_duration = int(float(duration_attr))
                    except:
                        video_duration = 0
        
        return {
            "url": post_url,
            "message_id": message_id,
            "text": text,
            "views": views,
            "reactions": reactions,
            "has_photo": has_photo,
            "has_video": has_video,
            "has_media": has_photo or has_video,
            "media_url": media_url,
            "media_type": media_type,
            "video_duration": video_duration,
            "datetime": post_datetime,
            "is_forwarded": is_forwarded,
            "has_external_links": False,
            "is_advertisement": False
        }

    def _parse_reactions(self, msg_div) -> int:
        total = 0
        
        reactions_div = msg_div.find("div", class_="tgme_widget_message_reactions")
        if not reactions_div:
            return 0
        
        for span in reactions_div.find_all("span", class_="tgme_reaction"):
            text = span.get_text(strip=True)
            if not text:
                continue
            match = re.search(r'[\d]+(?:[.,]\d+)?[KkMm]?$', text)
            if match:
                num = parse_number(match.group())
                if num > 0:
                    total += num
        
        if total == 0:
            scripts = msg_div.find_all("script", type="application/json")
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    total += self._extract_reactions_from_json(data)
                except:
                    pass
        
        return total

    def _extract_reactions_from_json(self, data, depth=0) -> int:
        if depth > 5:
            return 0
        total = 0
        if isinstance(data, dict):
            for key in ['reactions', 'reaction_count', 'count', 'total_reactions']:
                if key in data:
                    try:
                        if isinstance(data[key], (int, float)):
                            total += int(data[key])
                        elif isinstance(data[key], str):
                            total += parse_number(data[key])
                        elif isinstance(data[key], list):
                            for item in data[key]:
                                if isinstance(item, dict) and 'count' in item:
                                    total += int(item.get('count', 0))
                    except:
                        pass
            for value in data.values():
                total += self._extract_reactions_from_json(value, depth + 1)
        elif isinstance(data, list):
            for item in data:
                total += self._extract_reactions_from_json(item, depth + 1)
        return total

    async def download_media(self, media_url: str, save_path: str) -> bool:
        """Скачать медиафайл с правильными заголовками."""
        try:
            if not media_url:
                return False
            
            headers = {
                "User-Agent": Config.SCRAPER_USER_AGENT,
                "Referer": "https://t.me/",
                "Origin": "https://t.me",
                "Accept": "video/mp4,video/*,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "video",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
            }
            
            async with self.session.get(media_url, headers=headers, timeout=60, allow_redirects=True) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    if len(content) < 1000:
                        logger.warning(f"Downloaded file too small: {len(content)} bytes from {media_url}")
                        return False
                    with open(save_path, "wb") as f:
                        f.write(content)
                    logger.info(f"✅ Downloaded media to {save_path} ({len(content)} bytes)")
                    return True
                else:
                    logger.warning(f"❌ Failed to download media: HTTP {resp.status} for {media_url}")
                    return False
        except Exception as e:
            logger.error(f"Download error: {e}")
            return False