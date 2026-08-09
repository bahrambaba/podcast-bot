#!/usr/bin/env python3
"""
Koohnameh Podcast Bot v2
Triggered by "گزارش کانال‌های فعال امروز" post in @koohnameh.
Parses channels, fetches messages, filters, generates Persian podcast via NotebookLM.
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

LAST_PROCESSED_FILE = "last_processed_id.txt"
PENDING_NOTEBOOK_FILE = "pending_notebook.json"

EXCLUDE_KEYWORDS = [
    "کلاس", "دوره", "آموزش", "ثبت نام", "هزینه", "شهریه",
    "تور", "سفر", "طبیعت گردی", "گردشگری",
    "ساعت", "مکان", "محل تجمع",
]

JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
]


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# Last processed ID
# =============================================================================

def get_last_processed_id():
    try:
        with open(LAST_PROCESSED_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def save_last_processed_id(post_id):
    with open(LAST_PROCESSED_FILE, "w") as f:
        f.write(str(post_id))


# =============================================================================
# Pending notebook management
# =============================================================================

def get_pending_notebook():
    try:
        with open(PENDING_NOTEBOOK_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_pending_notebook(notebook_id, date_str):
    with open(PENDING_NOTEBOOK_FILE, "w") as f:
        json.dump({"notebook_id": notebook_id, "date_str": date_str}, f)


def clear_pending_notebook():
    try:
        os.remove(PENDING_NOTEBOOK_FILE)
    except FileNotFoundError:
        pass


# =============================================================================
# Find trigger post in @koohnameh
# =============================================================================

async def find_trigger_post(client, channel_username):
    try:
        entity = await client.get_entity(channel_username)
        async for msg in client.iter_messages(entity, limit=20):
            text = msg.text or ""
            if "گزارش کانال‌های فعال امروز" in text or "گزارش کانالهای فعال امروز" in text:
                return msg
    except Exception as e:
        logger.error(f"Error finding trigger post: {e}")
    return None


# =============================================================================
# Parse trigger post
# =============================================================================

def parse_trigger_post(text):
    """Extract Jalali date and channels from trigger post."""
    jalali_date = None
    date_match = re.search(
        r"(\d{1,2})\s+(فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)\s+(\d{4})",
        text,
    )
    if date_match:
        day, month, year = date_match.groups()
        jalali_date = f"{day} {month} {year}"

    channels = []
    channel_pattern = re.compile(r"@(\w+)")
    for line in text.split("\n"):
        if "@" in line:
            match = channel_pattern.search(line)
            if match:
                username = match.group(1)
                count_match = re.search(r"(\d+)\s*پیام", line)
                count = int(count_match.group(1)) if count_match else 0
                name_match = re.search(r"^(.*?)(?:\(@|$)", line)
                name = name_match.group(1).strip() if name_match else username
                channels.append((username, name, count))

    return jalali_date, channels


# =============================================================================
# Fetch messages
# =============================================================================

async def fetch_messages_from_channel(client, channel_username, since_date):
    from telethon import errors

    messages = []
    try:
        entity = await client.get_entity(channel_username)
        async for message in client.iter_messages(entity, limit=100):
            if message.date.replace(tzinfo=None) >= since_date:
                text = message.text or ""
                messages.append({
                    "id": message.id,
                    "date": message.date.isoformat(),
                    "text": text,
                    "has_media": message.media is not None,
                    "has_text": len(text.strip()) > 20,
                    "channel": channel_username,
                })
            else:
                break
    except errors.UsernameNotOccupiedError:
        logger.warning(f"Channel not found: {channel_username}")
    except errors.ChannelPrivateError:
        logger.warning(f"Channel is private: {channel_username}")
    except Exception as e:
        logger.error(f"Error fetching {channel_username}: {e}")
    return messages


# =============================================================================
# Filter messages
# =============================================================================

def filter_messages(messages, config):
    filters = config.get("filters", {})
    exclude_keywords = filters.get("exclude_keywords", EXCLUDE_KEYWORDS)
    min_caption_length = filters.get("min_caption_length", 50)
    filtered = []
    for msg in messages:
        text = msg.get("text", "")
        if not text or len(text.strip()) < min_caption_length:
            continue
        if any(keyword in text for keyword in exclude_keywords):
            continue
        if msg.get("has_media") and not msg.get("has_text"):
            continue
        filtered.append(msg)
    logger.info(f"Filtered {len(messages)} -> {len(filtered)} messages")
    return filtered


# =============================================================================
# Build source text
# =============================================================================

def build_source_text(jalali_date, filtered_messages):
    """Build structured source text for NotebookLM."""
    if not jalali_date:
        today_jalali = jdatetime.datetime.now()
        yesterday_jalali = today_jalali - jdatetime.timedelta(days=1)
        jalali_date = f"{yesterday_jalali.day} {JALALI_MONTHS[yesterday_jalali.month - 1]} {yesterday_jalali.year}"

    # Podcast date = day after the post date
    date_parts = jalali_date.split()
    day = int(date_parts[0])
    month_name = date_parts[1]
    year = int(date_parts[2])
    month_idx = JALALI_MONTHS.index(month_name) + 1

    podcast_jalali = jdatetime.date(year, month_idx, day) + jdatetime.timedelta(days=1)
    podcast_date = f"{podcast_jalali.day} {JALALI_MONTHS[podcast_jalali.month - 1]} {podcast_jalali.year}"

    # Group messages by channel
    channels = {}
    for msg in filtered_messages:
        ch = msg.get("channel", "نامشخص")
        if ch not in channels:
            channels[ch] = []
        channels[ch].append(msg.get("text", "")[:500])

    total_msgs = len(filtered_messages)
    active_channels = len(channels)

    # Build intro
    intro = f"""سلام و درود خدمت شنوندگان عزیز پادکست کوهنامه.
امروز تاریخ {podcast_date} هست و در تحریریه سایت کوهنامه با خلاصه‌ای از اخبار و نوشته‌های کوهنوردی که دیروز در فضای مجازی منتشر شده در خدمتتون هستیم.
خوب بریم با هم مروری داشته باشیم بر روی مطالب کانال‌های فعال دیروز."""

    # Build stats
    stats = f"\n\nآمار کلی: {total_msgs} پیام از {active_channels} کانال فعال"

    # Build content
    content = "\n\nمحتوای خبری:\n"
    for ch_name, msgs in channels.items():
        content += f"\nکانال {ch_name}:\n"
        for m in msgs[:5]:
            content += f"- {m}\n"

    # Build outro
    outro = f"""

امیدوارم از شنیدن این پادکست لذت برده باشید.
هر روز منتظر انتشار پادکست‌های صوتی روزانه از وبسایت تحلیلی خبری کوهنامه باشید.
تا پادکست بعدی، خدا نگهدارتون باشه."""

    source_text = intro + stats + content + outro
    return source_text, podcast_date, total_msgs, active_channels


# =============================================================================
# NotebookLM podcast generation (with retry + pending notebook)
# =============================================================================

async def generate_podcast(source_text, date_str, output_path):
    from notebooklm import NotebookLMClient
    from notebooklm.exceptions import RateLimitError

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

    # Check for pending notebook
    pending = get_pending_notebook()
    notebook_id = pending["notebook_id"] if pending else None

    try:
        async with NotebookLMClient.from_storage(keepalive=600) as client:
            logger.info("NotebookLM client created")

            if not notebook_id:
                # Create new notebook
                nb = await client.notebooks.create(title=f"پادکست کوهنامه {date_str}")
                notebook_id = nb.id
                logger.info(f"Notebook created: {notebook_id}")

                # Add source
                await client.sources.add_text(notebook_id, f"اخبار کوهنوردی {date_str}", source_text)
                logger.info("Source added")

                # Save pending notebook
                save_pending_notebook(notebook_id, date_str)
            else:
                logger.info(f"Using existing pending notebook: {notebook_id}")

            # Generate audio with retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    status = await client.artifacts.generate_audio(
                        notebook_id,
                        language="fa",
                        instructions=(
                            "این یک پادکست خبری فارسی درباره اخبار کوهنوردی و طبیعت ایران است. "
                            "دو نفر درباره اخبار کوهنوردی دیروز صحبت می‌کنند. "
                            "لطفاً به فارسی صحبت کنید."
                        ),
                    )
                    logger.info(f"Audio generation started: task_id={status.task_id}")

                    # Wait for completion
                    logger.info("Waiting for audio generation (up to 20 min)...")
                    await client.artifacts.wait_for_completion(notebook_id, status.task_id, timeout=1200)
                    logger.info("Audio generation completed!")

                    # Download
                    result = await client.artifacts.download_audio(notebook_id, output_path)
                    logger.info(f"Podcast saved: {result}")

                    # Cleanup notebook
                    try:
                        await client.notebooks.delete(notebook_id)
                        logger.info("Notebook deleted (cleanup)")
                    except Exception as e:
                        logger.warning(f"Could not delete notebook: {e}")

                    clear_pending_notebook()
                    return True

                except RateLimitError:
                    wait_time = (attempt + 1) * 300  # 5, 10, 15 min
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limited (attempt {attempt + 1}/{max_retries}). Waiting {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Rate limited after {max_retries} attempts. Will retry on next run.")
                        return False

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
        files = {"audio": audio}
        data = {
            "chat_id": chat_id,
            "caption": caption[:1024],
            "title": "پادکست کوهنامه",
            "performer": "کوهنامه",
        }
        resp = requests.post(url, files=files, data=data)
        if resp.status_code == 200:
            logger.info("Audio sent to Telegram successfully")
            return True
        else:
            logger.error(f"Telegram error: {resp.text}")
            return False


# =============================================================================
# Main
# =============================================================================

async def async_main():
    config = load_config()
    trigger_channel = config.get("koohnameh_username", "koohnameh")

    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH not set!")
        return

    from telethon import TelegramClient

    # === PENDING NOTEBOOK: retry audio generation ===
    pending = get_pending_notebook()
    if pending:
        logger.info(f"Found pending notebook: {pending['notebook_id']}. Retrying audio generation...")
        os.makedirs("output", exist_ok=True)
        output_path = f"output/podcast_{pending['date_str'].replace(' ', '_')}.m4a"
        success = await generate_podcast("", pending["date_str"], output_path)
        if success:
            caption = f"🎙️ پادکست کوهنامه\nتاریخ: {pending['date_str']}"
            send_to_telegram(output_path, caption)
            logger.info("Pending notebook completed successfully!")
        else:
            logger.info("Pending notebook still waiting. Will retry on next run.")
        return

    # === NEW TRIGGER POST ===
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

        # Parse trigger post
        trigger_text = trigger_msg.text or ""
        channels_jalali_date, channels = parse_trigger_post(trigger_text)

        if not channels:
            logger.warning("No channels parsed from trigger post.")
            await client.disconnect()
            return

        # Mark as processed IMMEDIATELY (before fetching)
        save_last_processed_id(trigger_msg.id)
        logger.info(f"Post {trigger_msg.id} marked as processed")

        # Fetch messages from each channel
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

        # Filter
        logger.info("Filtering messages...")
        filtered = filter_messages(messages, config)
        if not filtered:
            logger.warning("No messages after filtering. Using all fetched messages.")
            filtered = messages

        # Build source text
        source_text, podcast_date, total_msgs, active_channels = build_source_text(channels_jalali_date, filtered)
        logger.info(f"Source text built: {total_msgs} msgs from {active_channels} channels, date={podcast_date}")

        # Generate podcast
        logger.info("Generating podcast with NotebookLM...")
        os.makedirs("output", exist_ok=True)
        date_slug = podcast_date.replace(" ", "_")
        output_path = f"output/podcast_{date_slug}.m4a"

        success = await generate_podcast(source_text, podcast_date, output_path)
        if not success:
            logger.error("Podcast generation failed! Will retry on next run.")
            return

        # Send to Telegram
        logger.info("Sending to Telegram...")
        caption = f"🎙️ پادکست کوهنامه\nتاریخ: {podcast_date}\nتعداد پیام‌ها: {total_msgs} | کانال‌ها: {active_channels}"
        send_to_telegram(output_path, caption)

        logger.info("Done!")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await client.disconnect()
        except Exception:
            pass


def main():
    logger.info("Starting Koohnameh Podcast Bot v2...")
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
