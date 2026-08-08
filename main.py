#!/usr/bin/env python3
"""
Koohnameh Podcast Bot
Fetches mountain news from Telegram channels and generates Persian podcasts using NotebookLM.
"""

import requests
import json
import os
import re
import yaml
import logging
import asyncio
from datetime import datetime, timedelta
import jdatetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_config():
    """Load config.yaml"""
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# PART 1: Get channel list from config
# =============================================================================

def get_koohnameh_channels(config):
    """Fetch the channel list from config."""
    channels = []
    for ch in config.get('channels', []):
        channels.append((ch['name'], ch['username']))
    return channels


# =============================================================================
# PART 2: Read messages with Telethon
# =============================================================================

async def fetch_messages_from_channel(client, channel_username, since_date):
    """Fetch messages from a single channel."""
    from telethon import errors
    
    messages = []
    
    try:
        entity = await client.get_entity(channel_username)
        logger.info(f"  Entity found: {entity.title if hasattr(entity, 'title') else channel_username}")
        
        message_count = 0
        async for message in client.iter_messages(entity, limit=100):
            if message.date.replace(tzinfo=None) >= since_date:
                text = message.text or ""
                has_media = message.media is not None
                has_text = len(text.strip()) > 20
                
                messages.append({
                    "id": message.id,
                    "date": message.date.isoformat(),
                    "text": text,
                    "has_media": has_media,
                    "has_text": has_text,
                    "channel": channel_username
                })
                message_count += 1
            else:
                break
        
        logger.info(f"  Messages fetched: {message_count}")
        
    except errors.UsernameNotOccupiedError:
        logger.warning(f"  Channel not found: {channel_username}")
    except errors.ChannelPrivateError:
        logger.warning(f"  Channel is private: {channel_username}")
    except Exception as e:
        logger.error(f"  Error fetching {channel_username}: {e}")
    
    return messages


async def fetch_all_messages(channels, days_back=1):
    """Fetch messages from all channels."""
    from telethon import TelegramClient
    
    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    
    if not api_id or not api_hash:
        logger.warning("TELEGRAM_API_ID or TELEGRAM_API_HASH not set")
        return []
    
    messages = []
    
    async def get_messages():
        session_file = "bot_session.session"
        if os.path.exists(session_file):
            client = TelegramClient(session_file.replace('.session', ''), api_id, api_hash)
        else:
            client = TelegramClient('bot_session', api_id, api_hash)
        
        await client.start()
        
        since_date = (datetime.now() - timedelta(days=days_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        for channel_name, channel_username in channels:
            logger.info(f"Fetching: {channel_name} (@{channel_username})")
            channel_messages = await fetch_messages_from_channel(client, channel_username, since_date)
            messages.extend(channel_messages)
        
        await client.disconnect()
    
    await get_messages()
    return messages


# =============================================================================
# PART 3: Filter content
# =============================================================================

EXCLUDE_KEYWORDS = [
    "کلاس", "دوره", "آموزش", "ثبت نام", "هزینه", "شهریه",
    "تور", "سفر", "طبیعت گردی", "گردشگری",
    "ساعت", "مکان", "محل تجمع",
]

def filter_messages(messages, config):
    """Filter messages based on criteria."""
    filters = config.get('filters', {})
    exclude_keywords = filters.get('exclude_keywords', EXCLUDE_KEYWORDS)
    min_caption_length = filters.get('min_caption_length', 20)
    
    filtered = []
    
    for msg in messages:
        text = msg.get('text', '')
        
        if not text or len(text.strip()) < min_caption_length:
            continue
        
        if any(keyword in text for keyword in exclude_keywords):
            continue
        
        if msg.get('has_media') and not msg.get('has_text'):
            continue
        
        filtered.append(msg)
    
    logger.info(f"Filtered {len(messages)} -> {len(filtered)} messages")
    return filtered


# =============================================================================
# PART 4: Generate podcast with NotebookLM
# =============================================================================

async def generate_podcast_with_notebooklm(messages, config, output_path):
    """
    Generate podcast using NotebookLM.
    Returns True if successful.
    """
    from notebooklm import NotebookLMClient, AuthTokens
    
    # Prepare content
    content = "اخبار کوهنوردی دیروز:\n\n"
    
    channels = {}
    for msg in messages:
        ch = msg.get('channel', 'نامشخص')
        if ch not in channels:
            channels[ch] = []
        channels[ch].append(msg.get('text', '')[:500])
    
    for ch, msgs in channels.items():
        content += f"کانال {ch}:\n"
        for m in msgs[:5]:
            content += f"- {m}\n"
        content += "\n"
    
    # Calculate dates
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    
    yesterday_jalali = jdatetime.datetime.fromgregorian(datetime=yesterday)
    
    jalali_months = [
        'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
        'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'
    ]
    
    def format_jalali(dt):
        return f'{dt.day} {jalali_months[dt.month - 1]} {dt.year}'
    
    yesterday_jalali_str = format_jalali(yesterday_jalali)
    
    # Get auth tokens from environment
    cookies_str = os.environ.get("NOTEBOOKLM_COOKIES", "")
    csrf_token = os.environ.get("NOTEBOOKLM_CSRF", "")
    session_id = os.environ.get("NOTEBOOKLM_SESSION_ID", "")
    
    if not cookies_str:
        logger.error("NOTEBOOKLM_COOKIES not set!")
        logger.info("Please set these secrets:")
        logger.info("1. NOTEBOOKLM_COOKIES - Browser cookies from notebooklm.google.com")
        logger.info("2. NOTEBOOKLM_CSRF - CSRF token from browser")
        logger.info("3. NOTEBOOKLM_SESSION_ID - Session ID from browser")
        return False
    
    # Parse cookies
    cookies = {}
    for item in cookies_str.split(";"):
        if "=" in item:
            key, value = item.strip().split("=", 1)
            cookies[key] = value
    
    auth = AuthTokens(
        cookies=cookies,
        csrf_token=csrf_token,
        session_id=session_id
    )
    
    client = NotebookLMClient(auth)
    
    try:
        # Create notebook
        logger.info("Creating notebook...")
        nb = await client.notebooks.create(title=f"پادکست کوهنامه {yesterday_jalali_str}")
        logger.info(f"Notebook created: {nb.id}")
        
        # Add content as source
        logger.info("Adding source...")
        await client.sources.add_text(nb.id, content, title=f"اخبار {yesterday_jalali_str}")
        
        # Generate audio
        logger.info("Generating audio...")
        status = await client.artifacts.generate_audio(nb.id)
        
        # Wait for completion
        logger.info("Waiting for audio generation (may take a few minutes)...")
        await client.artifacts.wait_for_completion(nb.id, status.task_id)
        
        # Download audio
        logger.info("Downloading audio...")
        output = await client.artifacts.download_audio(nb.id, output_path)
        
        logger.info(f"Podcast saved: {output}")
        
        # Cleanup
        await client.notebooks.delete(nb.id)
        logger.info("Notebook deleted")
        
        return True
        
    except Exception as e:
        logger.error(f"NotebookLM error: {e}")
        return False


# =============================================================================
# PART 5: Send to Telegram
# =============================================================================

def send_to_telegram(audio_path, caption, config):
    """Send audio file to Telegram."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not set")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    
    with open(audio_path, "rb") as audio:
        files = {"audio": audio}
        data = {
            "chat_id": chat_id,
            "caption": caption[:1024],
            "title": "پادکست کوهنامه",
            "performer": "کوهنامه"
        }
        
        resp = requests.post(url, files=files, data=data)
        
        if resp.status_code == 200:
            logger.info("Audio sent to Telegram successfully")
            return True
        else:
            logger.error(f"Telegram error: {resp.text}")
            return False


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main function."""
    logger.info("Starting Koohnameh Podcast Bot...")
    
    # Load config
    config = load_config()
    
    # Step 1: Get channel list
    logger.info("\n📡 Step 1: Getting channel list...")
    channels = get_koohnameh_channels(config)
    logger.info(f"Found {len(channels)} channels")
    
    # Step 2: Fetch messages
    logger.info("\n📥 Step 2: Fetching messages...")
    messages = asyncio.run(fetch_all_messages(channels, days_back=1))
    logger.info(f"Total messages: {len(messages)}")
    
    if not messages:
        logger.warning("No messages found!")
        return
    
    # Step 3: Filter content
    logger.info("\n🔍 Step 3: Filtering content...")
    filtered_messages = filter_messages(messages, config)
    
    if not filtered_messages:
        logger.warning("No messages after filtering!")
        filtered_messages = messages[:20]
    
    # Step 4: Generate podcast with NotebookLM
    logger.info("\n🎙️ Step 4: Generating podcast with NotebookLM...")
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y%m%d")
    output_path = f"output/podcast_{yesterday_str}.m4a"
    os.makedirs("output", exist_ok=True)
    
    success = asyncio.run(generate_podcast_with_notebooklm(filtered_messages, config, output_path))
    
    if not success:
        logger.error("Failed to generate podcast")
        return
    
    # Step 5: Send to Telegram
    logger.info("\n📤 Step 5: Sending to Telegram...")
    yesterday_jalali = jdatetime.datetime.fromgregorian(datetime=yesterday)
    jalali_months = [
        'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
        'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'
    ]
    date_str = f"{yesterday_jalali.day} {jalali_months[yesterday_jalali.month - 1]} {yesterday_jalali.year}"
    
    caption = f"🎙️ پادکست کوهنامه\nتاریخ: {date_str}\tعداد پیام‌ها: {len(filtered_messages)}"
    send_to_telegram(output_path, caption, config)
    
    logger.info("\n✅ Done!")


if __name__ == "__main__":
    main()
