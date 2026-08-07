#!/usr/bin/env python3
"""
Koohnameh Podcast Bot
Fetches mountain news from Telegram channels and generates Persian podcasts.
"""

import feedparser
import requests
import json
import os
import re
import yaml
import logging
import subprocess
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_config():
    """Load configuration from config.yaml"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# PART 1: Get channel list from Koohnameh
# =============================================================================

def get_koohnameh_channels(config):
    """
    Fetch the channel list from config.
    Returns list of (channel_name, channel_username) tuples.
    """
    channels = []
    
    # Read from config.yaml
    known_channels = config.get("channels", {})
    
    for ch in known_channels:
        username = ch.get("username", "")
        name = ch.get("name", "")
        if username:
            channels.append((name, username))
    
    logger.info(f"Loaded {len(channels)} known channels")
    return channels


# =============================================================================
# PART 2: Fetch messages from channels (using Telethon)
# =============================================================================

def fetch_channel_messages(channel_username, days_back=1):
    """
    Fetch messages from a Telegram channel using Telethon.
    Returns list of messages.
    """
    try:
        from telethon import TelegramClient
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
        import asyncio
        
        api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
        api_hash = os.environ.get("TELEGRAM_API_HASH", "")
        session_name = os.environ.get("TELEGRAM_SESSION", "bot_session")
        
        if not api_id or not api_hash:
            logger.warning("TELEGRAM_API_ID or TELEGRAM_API_HASH not set")
            return []
        
        messages = []
        
        async def get_messages():
            client = TelegramClient(session_name, api_id, api_hash)
            await client.start()
            
            # Check if we're connected as user or bot
            me = await client.get_me()
            logger.info(f"Connected as: {me.first_name} (ID: {me.id})")
            
            # Calculate date filter
            since_date = datetime.now() - timedelta(days=days_back)
            
            # Get channel entity
            try:
                entity = await client.get_entity(channel_username)
                logger.info(f"  Entity found: {entity.title if hasattr(entity, 'title') else channel_username}")
                
                # Get messages
                message_count = 0
                async for message in client.iter_messages(
                    entity,
                    limit=100,
                ):
                    if message.date.replace(tzinfo=None) >= since_date:
                        # Check if has media
                        has_media = message.media is not None
                        has_caption = bool(message.text)
                        
                        # Get media type
                        media_type = None
                        if has_media:
                            if isinstance(message.media, MessageMediaPhoto):
                                media_type = "photo"
                            elif isinstance(message.media, MessageMediaDocument):
                                if message.media.document:
                                    for attr in message.media.document.attributes:
                                        if hasattr(attr, 'file_name'):
                                            if attr.file_name.endswith(('.mp4', '.avi', '.mov')):
                                                media_type = "video"
                                            elif attr.file_name.endswith(('.mp3', '.ogg', '.wav')):
                                                media_type = "audio"
                        
                        messages.append({
                            "id": message.id,
                            "date": message.date.isoformat(),
                            "text": message.text or "",
                            "has_media": has_media,
                            "has_caption": has_caption,
                            "media_type": media_type,
                            "views": message.views or 0,
                        })
                        message_count += 1
                    
                    # Stop if we went past our date range
                    if message.date.replace(tzinfo=None) < since_date:
                        break
                
                logger.info(f"  Messages fetched: {message_count}")
            
            except Exception as e:
                logger.error(f"Error fetching {channel_username}: {e}")
            
            await client.disconnect()
        
        # Run async function
        asyncio.run(get_messages())
        
        return messages
        
    except ImportError:
        logger.error("Telethon not installed. Run: pip install telethon")
        return []
    except Exception as e:
        logger.error(f"Error: {e}")
        return []


# =============================================================================
# PART 3: Filter content
# =============================================================================

def should_include_message(message, config):
    """
    Filter messages based on rules:
    - Exclude: class announcements, tours, nature trips
    - Exclude: images/videos without sufficient caption
    - Include: news and articles
    """
    text = message.get("text", "")
    media_type = message.get("media_type")
    has_caption = message.get("has_caption", False)
    
    # Filter keywords (Persian)
    exclude_keywords = [
        "کلاس", "دوره", "آموزش", "ثبت نام",
        "تور", "طبیعت گردی", "کمپینگ", "اردو",
        "برنامه هفتگی", "برنامه ماهانه",
        "اطلاعیه", "اعلامیه",
        "لغو", "تغییر برنامه",
    ]
    
    # Check exclude keywords
    for keyword in exclude_keywords:
        if keyword in text:
            return False
    
    # Check media without caption
    if media_type in ["photo", "video"] and not has_caption:
        return False
    
    # Check for very short captions (less than 20 chars)
    if has_caption and len(text.strip()) < 20:
        return False
    
    # Include if has meaningful text
    if text and len(text.strip()) > 20:
        return True
    
    return False


# =============================================================================
# PART 4: Generate podcast with Gemini
# =============================================================================

def generate_podcast_content(messages, config):
    """
    Generate podcast script using Gemini API.
    Returns podcast script in Persian.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        return None
    
    # Prepare messages summary
    messages_text = ""
    for i, msg in enumerate(messages[:50], 1):  # Limit to 50 messages
        messages_text += f"{i}. {msg['text'][:500]}\n\n"
    
    # Count channels
    channels = set(msg.get('channel', '') for msg in messages)
    
    # Calculate dates
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    
    # Persian date (Jalali approximation)
    jalali_months = [
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
    ]
    # Simple approximation for display
    jalali_day = yesterday.day
    jalali_month = jalali_months[yesterday.month - 1] if yesterday.month <= 12 else "مرداد"
    jalali_year = 1405  # Fixed for now, should be calculated
    
    # Create prompt
    prompt = f"""شما یک مجری برنامه صبحگاهی کوهنوردی هستید.

تاریخ امروز: {today.strftime('%Y/%m/%d')}
تاریخ دیروز (روز اخبار): {yesterday.strftime('%Y/%m/%d')}
تاریخ شمسی دیروز: {jalali_day} {jalali_month} {jalali_year}

تعداد پیام‌های دریافتی: {len(messages)}
تعداد کانال‌های فعال: {len(channels)}

لطفاً خلاصه اخبار کوهنوردی دیروز ({yesterday.strftime('%Y/%m/%d')}) را به صورت یک متن پادکست بنویسید.

قوانین:
۱. با سلام و احوالپرسی شروع کنید
۲. تاریخ دیروز را دقیقاً ذکر کنید ( هم شمسی هم میلادی)
۳. اخبار مهم را به صورت خلاصه بیان کنید
۴. لحن صمیمی و حرفه‌ای داشته باشید
۵. حدود ۱۵-۲۰ دقیقه صحبت کنید
۶. از اصطلاحات تخصصی پرهیز کنید
۷. در پایان از مخاطبان خداحافظی کنید

اخبار:
{messages_text}

لطفاً متن پادکست را بنویسید:"""
    
    # Call Gemini API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8000,
        }
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=120)
        data = resp.json()
        
        if "candidates" in data and data["candidates"]:
            script = data["candidates"][0]["content"]["parts"][0]["text"]
            logger.info(f"Generated script: {len(script)} chars")
            return script
        else:
            logger.error(f"Gemini error: {data}")
            return None
            
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return None


def generate_audio(script, output_path, config):
    """
    Generate audio from script using Gemini TTS.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        return False
    
    # Gemini TTS API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": f"لطفاً این متن را با لحن صمیمی و حرفه‌ای بخوانید:\n\n{script}"
            }]
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": "Aoede"
                    }
                }
            }
        }
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=300)
        data = resp.json()
        
        if "candidates" in data and data["candidates"]:
            # Extract audio data
            audio_data = data["candidates"][0]["content"]["parts"][0]
            if "inlineData" in audio_data:
                import base64
                audio_bytes = base64.b64decode(audio_data["inlineData"]["data"])
                
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                
                logger.info(f"Audio saved: {output_path}")
                return True
        
        logger.error(f"TTS error: {data}")
        return False
        
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return False


# =============================================================================
# PART 5: Send to Telegram
# =============================================================================

def send_telegram_audio(bot_token, chat_id, audio_path, caption=""):
    """Send audio file to Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    
    try:
        with open(audio_path, "rb") as audio:
            files = {"audio": audio}
            data = {
                "chat_id": chat_id,
                "caption": caption[:1024],
                "title": "پادکست کوهنوردی",
            }
            resp = requests.post(url, data=data, files=files, timeout=120)
            
            if resp.status_code == 200:
                logger.info("Audio sent to Telegram successfully")
                return True
            else:
                logger.error(f"Telegram error: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main function."""
    logger.info("=" * 60)
    logger.info("KOOHNAMEH PODCAST BOT")
    logger.info("=" * 60)
    
    # Load config
    config = load_config()
    
    # Step 1: Get channel list
    logger.info("\n📡 Step 1: Getting channel list...")
    channels = get_koohnameh_channels(config)
    logger.info(f"Found {len(channels)} channels")
    
    # Step 2: Fetch messages
    logger.info("\n📥 Step 2: Fetching messages...")
    all_messages = []
    
    for name, username in channels:
        messages = fetch_channel_messages(username, days_back=1)
        for msg in messages:
            msg["channel"] = name
            msg["channel_username"] = username
        all_messages.extend(messages)
        logger.info(f"  {name}: {len(messages)} messages")
    
    logger.info(f"Total messages: {len(all_messages)}")
    
    # Step 3: Filter
    logger.info("\n🔍 Step 3: Filtering content...")
    filtered = [m for m in all_messages if should_include_message(m, config)]
    logger.info(f"After filtering: {len(filtered)} messages")
    
    if not filtered:
        logger.warning("No messages to include in podcast")
        return
    
    # Step 4: Generate podcast script
    logger.info("\n📝 Step 4: Generating podcast script...")
    script = generate_podcast_content(filtered, config)
    
    if not script:
        logger.error("Failed to generate script")
        return
    
    # Step 5: Generate audio
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d")
    script_path = os.path.join(output_dir, f"script_{timestamp}.txt")
    audio_path = os.path.join(output_dir, f"podcast_{timestamp}.mp3")
    
    # Save script
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    logger.info(f"Script saved: {script_path}")
    
    logger.info("\n🎙️ Step 5: Generating audio...")
    success = generate_audio(script, audio_path, config)
    
    if not success or not os.path.exists(audio_path):
        logger.error("Failed to generate audio")
        return
    
    # Step 6: Send to Telegram
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if bot_token and chat_id:
        logger.info("\n📤 Step 6: Sending to Telegram...")
        channels_count = len(set(m.get("channel") for m in filtered))
        caption = (
            f"🎙️ پادکست اخبار کوهنوردی\n"
            f"📅 {datetime.now().strftime('%Y/%m/%d')}\n"
            f"📨 {len(filtered)} پیام از {channels_count} کانال"
        )
        send_telegram_audio(bot_token, chat_id, audio_path, caption)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    
    # Save results
    results = {
        "date": datetime.now().isoformat(),
        "total_messages": len(all_messages),
        "filtered_messages": len(filtered),
        "channels_count": channels_count,
        "script_length": len(script),
        "script_path": script_path,
        "audio_path": audio_path,
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n✅ Done! Podcast saved to: {audio_path}")


if __name__ == "__main__":
    main()
