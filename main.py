#!/usr/bin/env python3
"""
Koohnameh Podcast Bot v2 — Trigger-based architecture.

Checks @koohnameh for the daily trigger post, parses channel list,
fetches messages, filters, generates a NotebookLM podcast, and sends to Telegram.
"""

import os
import re
import json
import yaml
import logging
import asyncio
import requests
from datetime import datetime, timedelta
from pathlib import Path

import jdatetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TRIGGER_KEYWORD = "گزارش کانال‌های فعال امروز"
LAST_PROCESSED_FILE = "last_processed_id.txt"

# Jalali month names
JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

# Persian digit map
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def fa_to_int(s: str) -> int:
    """Convert Persian/Arabic numerals to int."""
    return int(s.translate(FA_DIGITS))


def jalali_plus_one(dt: jdatetime.datetime) -> jdatetime.datetime:
    """Add one day to a Jalali datetime."""
    greg = dt.togregorian()
    new_greg = greg + timedelta(days=1)
    return jdatetime.datetime.fromgregorian(datetime=new_greg)


def format_jalali(dt: jdatetime.datetime) -> str:
    return f"{dt.day} {JALALI_MONTHS[dt.month - 1]} {dt.year}"


def format_jalali_date_only(date_str: str) -> str:
    """Parse Jalali date string like '۱۴۰۴/۰۵/۱۷' or '1404/05/17' and return formatted."""
    parts = re.split(r"[/\-]", date_str.strip())
    if len(parts) == 3:
        y, m, d = fa_to_int(parts[0]), fa_to_int(parts[1]), fa_to_int(parts[2])
        dt = jdatetime.date(y, m, d)
        dt_plus = jdatetime.date(y, m, d) + timedelta(days=1)
        return f"{dt_plus.day} {JALALI_MONTHS[dt_plus.month - 1]} {dt_plus.year}"
    return ""


# =============================================================================
# Config
# =============================================================================

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# Trigger post detection & parsing
# =============================================================================

async def find_trigger_post(client, trigger_channel):
    """Find the latest post in trigger_channel containing the trigger keyword."""
    entity = await client.get_entity(trigger_channel)
    async for msg in client.iter_messages(entity, limit=20):
        text = msg.text or ""
        if TRIGGER_KEYWORD in text:
            logger.info(f"Found trigger post (id={msg.id}) in @{trigger_channel}")
            return msg
    return None


def parse_trigger_post(text: str):
    """
    Parse trigger post to extract:
    - jalali_date: the date string from the post
    - channels: list of (username, name_hint, msg_count)
    """
    # Extract Jalali date (pattern like ۱۴۰۴/۰۵/۱۷ or 1404/05/17)
    date_match = re.search(r"(\d{4}[\s/\-]\d{1,2}[\s/\-]\d{1,2})", text)
    jalali_date = date_match.group(1) if date_match else ""

    # Extract channels: @username with optional name and message count
    # Patterns: "@chakadclub — ۱۵ پیام" or "@chakadclub: 15" or just "@chakadclub"
    channels = []
    # Find all @usernames
    for m in re.finditer(r"@(\w+)", text):
        username = m.group(1)
        # Look for a number near this mention (same line)
        line = text[max(0, m.start() - 5):min(len(text), text.index("\n", m.end()) if "\n" in text[m.end():] else len(text))]
        count_match = re.search(r"(\d+)", line)
        msg_count = int(count_match.group(1)) if count_match else 0
        channels.append((username, username, msg_count))

    logger.info(f"Parsed {len(channels)} channels from trigger post, date={jalali_date}")
    return jalali_date, channels


# =============================================================================
# Fetch messages with Telethon
# =============================================================================

async def fetch_messages_from_channel(client, channel_username, since_date):
    from telethon import errors
    messages = []
    try:
        entity = await client.get_entity(channel_username)
        title = getattr(entity, "title", channel_username)
        count = 0
        async for message in client.iter_messages(entity, limit=100):
            msg_date = message.date.replace(tzinfo=None)
            if msg_date >= since_date:
                text = message.text or ""
                messages.append({
                    "id": message.id,
                    "date": message.date.isoformat(),
                    "text": text,
                    "has_media": message.media is not None,
                    "channel": channel_username,
                    "channel_name": title,
                })
                count += 1
            else:
                break
        logger.info(f"  @{channel_username} ({title}): {count} messages")
    except errors.UsernameNotOccupiedError:
        logger.warning(f"  Channel not found: @{channel_username}")
    except errors.ChannelPrivateError:
        logger.warning(f"  Channel is private: @{channel_username}")
    except Exception as e:
        logger.error(f"  Error fetching @{channel_username}: {e}")
    return messages


async def fetch_all_messages(channels, since_date):
    from telethon import TelegramClient
    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH not set")
        return []

    session_file = "bot_session"
    client = TelegramClient(session_file, api_id, api_hash)
    await client.start()

    all_messages = []
    for username, name, _count in channels:
        msgs = await fetch_messages_from_channel(client, username, since_date)
        all_messages.extend(msgs)

    await client.disconnect()
    return all_messages


# =============================================================================
# Filter messages
# =============================================================================

EXCLUDE_KEYWORDS = [
    "کلاس", "دوره", "آموزش", "ثبت نام", "هزینه", "شهریه",
    "تور", "سفر", "طبیعت گردی", "گردشگری",
    "ساعت", "مکان", "محل تجمع",
]


def filter_messages(messages, config):
    exclude_kw = config.get("filters", {}).get("exclude_keywords", EXCLUDE_KEYWORDS)
    min_text = config.get("filters", {}).get("min_caption_length", 50)
    filtered = []
    for msg in messages:
        text = msg.get("text", "").strip()
        # Exclude very short messages
        if len(text) < min_text:
            continue
        # Exclude messages with class/course/tour keywords
        if any(kw in text for kw in exclude_kw):
            continue
        filtered.append(msg)
    logger.info(f"Filtered {len(messages)} -> {len(filtered)} messages (min_text={min_text})")
    return filtered


# =============================================================================
# Build NotebookLM source text
# =============================================================================

def build_source_text(channels_jalali_date, filtered_messages):
    """
    Build structured source text for NotebookLM podcast generation.
    channels_jalali_date: the Jalali date string from the trigger post
    """
    # Determine podcast date = trigger date + 1
    podcast_date_str = format_jalali_date_only(channels_jalali_date) if channels_jalali_date else ""
    if not podcast_date_str:
        # Fallback: yesterday in Jalali
        yesterday = datetime.utcnow() - timedelta(days=1)
        jd = jdatetime.datetime.fromgregorian(datetime=yesterday)
        jd_plus = jalali_plus_one(jd)
        podcast_date_str = format_jalali(jd_plus)

    # Group messages by channel
    by_channel = {}
    for msg in filtered_messages:
        ch = msg.get("channel_name") or msg.get("channel", "نامشخص")
        by_channel.setdefault(ch, []).append(msg["text"])

    total_msgs = sum(len(v) for v in by_channel.values())
    active_channels = len(by_channel)

    # INTRO
    intro = (
        f"سلام و درود خدمت شنوندگان عزیز پادکست کوهنامه. "
        f"امروز تاریخ {podcast_date_str} هست و در تحریریه سایت کوهنامه با خلاصه‌ای از اخبار و نوشته‌های کوهنوردی که دیروز در فضای مجازی منتشر شده در خدمتتون هستیم. "
        f"خوب بریم با هم مروری داشته باشیم بر روی مطالب کانال‌های فعال دیروز."
    )

    # STATS
    stats = f"تعداد کل پیام‌های منتشر شده: {total_msgs} پیام از {active_channels} کانال فعال."

    # CONTENT
    content_parts = []
    for ch_name, msgs in by_channel.items():
        ch_text = f"\n---\nکانال {ch_name}:\n"
        for m in msgs:
            ch_text += f"{m[:500]}\n\n"
        content_parts.append(ch_text)
    content = "\n".join(content_parts)

    # OUTRO
    outro = (
        "امیدوارم از شنیدن این پادکست لذت برده باشید. "
        "هر روز منتظر انتشار پادکست‌های صوتی روزانه از وبسایت تحلیلی خبری کوهنامه باشید. "
        "تا پادکست بعدی، خدا نگهدارتون باشه."
    )

    full_text = f"{intro}\n\n{stats}\n\n{content}\n\n{outro}"
    return full_text, podcast_date_str, total_msgs, active_channels


# =============================================================================
# NotebookLM podcast generation
# =============================================================================

async def generate_podcast(source_text, date_str, output_path):
    from notebooklm import NotebookLMClient

    auth_json = os.environ.get("NOTEBOOKLM_AUTH_JSON", "")
    if not auth_json:
        logger.error("NOTEBOOKLM_AUTH_JSON not set!")
        return False

    profile_dir = os.path.expanduser("~/.notebooklm/profiles/default")
    os.makedirs(profile_dir, exist_ok=True)

    storage_path = os.path.join(profile_dir, "storage_state.json")
    with open(storage_path, "w") as f:
        f.write(auth_json)
    os.chmod(storage_path, 0o600)

    master_token = os.environ.get("NOTEBOOKLM_MASTER_TOKEN", "")
    if master_token:
        token_path = os.path.join(profile_dir, "master_token.json")
        with open(token_path, "w") as f:
            f.write(master_token)
        os.chmod(token_path, 0o600)

    try:
        async with NotebookLMClient.from_storage(keepalive=600) as client:
            logger.info("NotebookLM client created")

            # Create notebook
            nb = await client.notebooks.create(title=f"پادکست کوهنامه {date_str}")
            logger.info(f"Notebook created: {nb.id}")

            # Add source
            await client.sources.add_text(nb.id, f"اخبار کوهنوردی {date_str}", source_text)
            logger.info("Source added")

            # Generate audio
            status = await client.artifacts.generate_audio(
                nb.id,
                language="fa",
                instructions="این یک پادکست خبری فارسی درباره اخبار کوهنوردی و طبیعت ایران است. دو نفر درباره اخبار کوهنوردی دیروز صحبت می‌کنند. لطفاً به فارسی صحبت کنید.",
            )
            logger.info(f"Audio generation started: task_id={status.task_id}")

            # Wait for completion
            logger.info("Waiting for audio generation (up to 20 min)...")
            await client.artifacts.wait_for_completion(nb.id, status.task_id, timeout=1200)
            logger.info("Audio generation completed!")

            # Download
            result = await client.artifacts.download_audio(nb.id, output_path)
            logger.info(f"Podcast saved: {result}")

            # Cleanup
            try:
                await client.notebooks.delete(nb.id)
                logger.info("Notebook deleted (cleanup)")
            except Exception as e:
                logger.warning(f"Could not delete notebook: {e}")

        return True
    except Exception as e:
        logger.error(f"NotebookLM error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# =============================================================================
# Send to Telegram
# =============================================================================

def send_to_telegram(audio_path, caption):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not set")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    with open(audio_path, "rb") as audio:
        resp = requests.post(
            url,
            files={"audio": audio},
            data={"chat_id": chat_id, "caption": caption[:1024], "title": "پادکست کوهنامه", "performer": "کوهنامه"},
        )
    if resp.status_code == 200:
        logger.info("Audio sent to Telegram")
        return True
    logger.error(f"Telegram error: {resp.text}")
    return False


# =============================================================================
# Last processed ID tracking
# =============================================================================

def get_last_processed_id():
    if os.path.exists(LAST_PROCESSED_FILE):
        return Path(LAST_PROCESSED_FILE).read_text().strip()
    return ""


def save_last_processed_id(post_id):
    Path(LAST_PROCESSED_FILE).write_text(str(post_id))


# =============================================================================
# Fallback: use hardcoded channels if no trigger found
# =============================================================================

def get_fallback_channels(config):
    channels = []
    for ch in config.get("channels", []):
        channels.append((ch["username"], ch.get("name", ch["username"]), 0))
    return channels


# =============================================================================
# Main
# =============================================================================

async def run_bot():
    config = load_config()
    trigger_channel = config.get("koohnameh_username", "koohnameh")
    trigger_channel = trigger_channel.lstrip("@")

    # Step 1: Connect to Telegram and check for trigger post
    from telethon import TelegramClient

    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH not set")
        return

    client = TelegramClient("bot_session", api_id, api_hash)
    await client.start()

    try:
        logger.info(f"Checking @{trigger_channel} for trigger post...")
        trigger_msg = await find_trigger_post(client, trigger_channel)

        if not trigger_msg:
            logger.info("No trigger post found. Exiting silently.")
            await client.disconnect()
            return

        # Check if already processed
        last_id = get_last_processed_id()
        if str(trigger_msg.id) == last_id:
            logger.info(f"Post {trigger_msg.id} already processed. Skipping.")
            await client.disconnect()
            return

        # Step 2: Parse trigger post
        trigger_text = trigger_msg.text or ""
        channels_jalali_date, channels = parse_trigger_post(trigger_text)

        if not channels:
            logger.warning("No channels parsed from trigger post. Using fallback.")
            channels = get_fallback_channels(config)

        # Step 3: Fetch messages from each channel (last 24h)
        logger.info(f"Fetching messages from {len(channels)} channels...")
        since_date = (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        messages = []
        for username, name, _count in channels:
            msgs = await fetch_messages_from_channel(client, username, since_date)
            messages.extend(msgs)

        await client.disconnect()
        logger.info(f"Total messages fetched: {len(messages)}")

        if not messages:
            logger.warning("No messages found. Nothing to podcast.")
            return

        # Step 4: Filter
        logger.info("Filtering messages...")
        filtered = filter_messages(messages, config)
        if not filtered:
            logger.warning("No messages after filtering. Using all fetched messages.")
            filtered = messages

        # Step 5: Build source text
        source_text, podcast_date, total_msgs, active_channels = build_source_text(channels_jalali_date, filtered)
        logger.info(f"Source text built: {total_msgs} msgs from {active_channels} channels, date={podcast_date}")

        # Step 6: Generate podcast via NotebookLM
        logger.info("Generating podcast with NotebookLM...")
        os.makedirs("output", exist_ok=True)
        date_slug = podcast_date.replace(" ", "_")
        output_path = f"output/podcast_{date_slug}.m4a"

        success = await generate_podcast(source_text, podcast_date, output_path)
        if not success:
            logger.error("Podcast generation failed!")
            return

        # Step 7: Send to Telegram
        logger.info("Sending to Telegram...")
        caption = f"🎙️ پادکست کوهنامه\nتاریخ: {podcast_date}\nتعداد پیام‌ها: {total_msgs} | کانال‌ها: {active_channels}"
        send_to_telegram(output_path, caption)

        # Step 8: Mark as processed
        save_last_processed_id(trigger_msg.id)
        logger.info("✅ Done!")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Disconnect if still connected
        try:
            await client.disconnect()
        except Exception:
            pass


def main():
    logger.info("Starting Koohnameh Podcast Bot v2...")
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
