#!/usr/bin/env python3
"""
Koohnameh Podcast Bot v3
Every day at 8 AM Iran time: check all channels, filter, generate Persian podcast via NotebookLM.
"""

import requests
import json
import os
import yaml
import logging
import asyncio
from datetime import datetime, timedelta
import jdatetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
]


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# Fetch messages from a single channel
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
        logger.warning(f"Channel not found: @{channel_username}")
    except errors.ChannelPrivateError:
        logger.warning(f"Channel is private: @{channel_username}")
    except errors.FloodWaitError as e:
        logger.warning(f"Flood wait for @{channel_username}: {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logger.error(f"Error fetching @{channel_username}: {e}")
    return messages


# =============================================================================
# Filter messages
# =============================================================================

def filter_messages(messages, config):
    filters = config.get("filters", {})
    exclude_keywords = filters.get("exclude_keywords", [])
    min_caption_length = filters.get("min_caption_length", 50)

    filtered = []
    seen_texts = set()  # Deduplicate

    for msg in messages:
        text = msg.get("text", "").strip()
        if not text or len(text) < min_caption_length:
            continue
        if any(keyword in text for keyword in exclude_keywords):
            continue
        if msg.get("has_media") and not msg.get("has_text"):
            continue

        # Deduplicate by first 100 chars
        text_key = text[:100]
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)

        filtered.append(msg)

    logger.info(f"Filtered {len(messages)} -> {len(filtered)} messages (deduped)")
    return filtered


# =============================================================================
# Build source text
# =============================================================================

def build_source_text(filtered_messages):
    """Build structured source text for NotebookLM."""
    today_jalali = jdatetime.datetime.now()
    yesterday_jalali = today_jalali - jdatetime.timedelta(days=1)
    yesterday_date = f"{yesterday_jalali.day} {JALALI_MONTHS[yesterday_jalali.month - 1]} {yesterday_jalali.year}"
    podcast_date = f"{today_jalali.day} {JALALI_MONTHS[today_jalali.month - 1]} {today_jalali.year}"

    # Group messages by channel
    channels = {}
    for msg in filtered_messages:
        ch = msg.get("channel", "نامشخص")
        if ch not in channels:
            channels[ch] = []
        channels[ch].append(msg.get("text", "")[:500])

    total_msgs = len(filtered_messages)
    active_channels = len(channels)

    # Intro
    intro = f"""سلام و درود خدمت شنوندگان عزیز پادکست کوهنامه.
امروز تاریخ {podcast_date} هست و در تحریریه سایت کوهنامه با خلاصه‌ای از اخبار و نوشته‌های کوهنوردی که دیروز ({yesterday_date}) در فضای مجازی منتشر شده در خدمتتون هستیم.
خوب بریم با هم مروری داشته باشیم بر روی مطالب کانال‌های فعال دیروز."""

    # Stats
    stats = f"\n\nآمار کلی: {total_msgs} پیام از {active_channels} کانال فعال"

    # Content
    content = "\n\nمحتوای خبری:\n"
    for ch_name, msgs in channels.items():
        content += f"\nکانال {ch_name}:\n"
        for m in msgs[:5]:
            content += f"- {m}\n"

    # Outro
    outro = """

امیدوارم از شنیدن این پادکست لذت برده باشید.
هر روز منتظر انتشار پادکست‌های صوتی روزانه از وبسایت تحلیلی خبری کوهنامه باشید.
تا پادکست بعدی، خدا نگهدارتون باشه."""

    source_text = intro + stats + content + outro
    return source_text, podcast_date, total_msgs, active_channels


# =============================================================================
# NotebookLM podcast generation
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

    try:
        async with NotebookLMClient.from_storage(keepalive=600) as client:
            logger.info("NotebookLM client created")

            nb = await client.notebooks.create(title=f"پادکست کوهنامه {date_str}")
            logger.info(f"Notebook created: {nb.id}")

            await client.sources.add_text(nb.id, f"اخبار کوهنوردی {date_str}", source_text)
            logger.info("Source added")

            status = await client.artifacts.generate_audio(
                nb.id,
                language="fa",
                instructions=(
                    "این یک پادکست خبری فارسی درباره اخبار کوهنوردی و طبیعت ایران است. "
                    "دو نفر درباره اخبار کوهنوردی دیروز صحبت می‌کنند. "
                    "لطفاً به فارسی صحبت کنید."
                ),
            )
            logger.info(f"Audio generation started: task_id={status.task_id}")

            logger.info("Waiting for audio generation (up to 20 min)...")
            await client.artifacts.wait_for_completion(nb.id, status.task_id, timeout=1200)
            logger.info("Audio generation completed!")

            result = await client.artifacts.download_audio(nb.id, output_path)
            logger.info(f"Podcast saved: {result}")

            try:
                await client.notebooks.delete(nb.id)
                logger.info("Notebook deleted (cleanup)")
            except Exception as e:
                logger.warning(f"Could not delete notebook: {e}")

        return True

    except RateLimitError:
        logger.error("Rate limited by NotebookLM. Will retry tomorrow.")
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
    channels = config.get("channels", [])

    if not channels:
        logger.error("No channels configured!")
        return

    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH not set!")
        return

    from telethon import TelegramClient

    client = TelegramClient("bot_session", api_id, api_hash)
    await client.start()

    try:
        # Fetch messages from all channels (last 24h)
        logger.info(f"Fetching messages from {len(channels)} channels...")
        since_date = (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        messages = []
        for ch in channels:
            username = ch if isinstance(ch, str) else ch.get("username", "")
            if username.startswith("@"):
                username = username[1:]
            msgs = await fetch_messages_from_channel(client, username, since_date)
            messages.extend(msgs)
            await asyncio.sleep(1)  # Rate limit respect

        await client.disconnect()
        logger.info(f"Total messages fetched: {len(messages)}")

        if not messages:
            logger.warning("No messages found. Nothing to podcast.")
            return

        # Filter
        logger.info("Filtering messages...")
        filtered = filter_messages(messages, config)
        if not filtered:
            logger.warning("No messages after filtering.")
            return

        # Build source text
        source_text, podcast_date, total_msgs, active_channels = build_source_text(filtered)
        logger.info(f"Source text built: {total_msgs} msgs from {active_channels} channels, date={podcast_date}")

        # Generate podcast
        logger.info("Generating podcast with NotebookLM...")
        os.makedirs("output", exist_ok=True)
        date_slug = podcast_date.replace(" ", "_")
        output_path = f"output/podcast_{date_slug}.m4a"

        success = await generate_podcast(source_text, podcast_date, output_path)
        if not success:
            logger.error("Podcast generation failed!")
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
    logger.info("Starting Koohnameh Podcast Bot v3...")
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
