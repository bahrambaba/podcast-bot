#!/usr/bin/env python3
"""
Koohnameh Podcast Bot v5
Gemini 2.5 Flash Native Audio Dialog for direct audio generation.
No edge-tts, no NotebookLM. Native audio from Gemini Live API.
"""

import asyncio
import json
import os
import re
import wave
import yaml
import logging
import requests
from datetime import datetime, timedelta
import jdatetime
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
SAMPLE_RATE = 24000
VOICE_FARID = "Charon"       # Informative male
VOICE_DILARA = "Aoede"      # Breezy female
SPEAKER_MALE = "فرشید"
SPEAKER_FEMALE = "پریسا"


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
        if e.seconds > 300:
            logger.warning(f"Flood wait {e.seconds}s too long for @{channel_username}, skipping")
            return messages
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
    seen_texts = set()
    for msg in messages:
        text = msg.get("text", "").strip()
        if not text or len(text) < min_caption_length:
            continue
        if any(kw in text for kw in exclude_keywords):
            continue
        if msg.get("has_media") and not msg.get("has_text"):
            continue
        key = text[:100]
        if key in seen_texts:
            continue
        seen_texts.add(key)
        filtered.append(msg)
    logger.info(f"Filtered {len(messages)} -> {len(filtered)} messages (deduped)")
    return filtered


# =============================================================================
# Build source text
# =============================================================================

def build_source_text(filtered_messages):
    today_jalali = jdatetime.datetime.now()
    yesterday_jalali = today_jalali - jdatetime.timedelta(days=1)
    yesterday_date = f"{yesterday_jalali.day} {JALALI_MONTHS[yesterday_jalali.month - 1]} {yesterday_jalali.year}"
    podcast_date = f"{today_jalali.day} {JALALI_MONTHS[today_jalali.month - 1]} {today_jalali.year}"

    channels = {}
    for msg in filtered_messages:
        ch = msg.get("channel", "نامشخص")
        channels.setdefault(ch, []).append(msg.get("text", "")[:500])

    total_msgs = len(filtered_messages)
    active_channels = len(channels)

    text_parts = [f"آمار: {total_msgs} پیام از {active_channels} کانال فعال.\n"]
    for ch_name, msgs in channels.items():
        text_parts.append(f"\nکانال @{ch_name}:")
        for m in msgs[:5]:
            text_parts.append(f"- {m}")

    return "\n".join(text_parts), podcast_date, total_msgs, active_channels


# =============================================================================
# Generate podcast script via Gemini text model
# =============================================================================

def generate_podcast_script(source_text, podcast_date):
    """Use Gemini to turn raw news text into a podcast dialogue script."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set!")
        return None

    client = genai.Client(api_key=api_key)

    prompt = f"""تو نویسنده حرفه‌ای پادکست هستی. متن اخبار زیر را به یک دیالوگ پادکست بلند تبدیل کن.

قوانین:
- دو مجری صحبت می‌کنند: {SPEAKER_MALE} (مذکر) و {SPEAKER_FEMALE} (مونث)
- لحن گرم و صمیمی، انرژی‌بخش، مثل یک برنامه صبحگاهی
- شروع دقیقاً با:
{SPEAKER_MALE}: سلام و درود خدمت شنوندگان عزیز پادکست کوهنامه.
{SPEAKER_FEMALE}: امروز تاریخ {podcast_date} هست و در تحریریه سایت کوهنامه با خلاصه‌ای از اخبار و نوشته‌های کوهنوردی که دیروز در فضای مجازی منتشر شده در خدمتتون هستیم.
{SPEAKER_MALE}: خوب بریم با هم مروری داشته باشیم بر روی مطالب کانال‌های فعال دیروز.

- بعد از معرفی، اخبار را به ترتیب روایت کن. هر خبر را یکی از مجری‌ها می‌گوید و دیگری کامنت کوتاه می‌گذارد.
- اخبار را با کلمات خودت و لحن صمیمی روایت کن، نه کپی متن.
- هر خبر را با جزئیات بیشتر و تحلیل کوتاه بیان کن تا پادکست طولانی‌تر شود.
- برای هر خبر حداقل ۳-۴ جمله صحبت کنید.
- حداقل ۲۰ خط دیالوگ تولید کن.
- در انتها:
{SPEAKER_MALE}: امیدوارم از شنیدن این پادکست لذت برده باشید.
{SPEAKER_FEMALE}: هر روز منتظر انتشار پادکست‌های صوتی روزانه از وبسایت تحلیلی خبری کوهنامه باشید.
{SPEAKER_MALE}: تا پادکست بعدی، خدا نگهدارتون باشه.

- فقط دیالوگ خروجی بده، هیچ توضیح اضافه نده.
- هر خط با اسم مجری شروع شود: {SPEAKER_MALE}: ... یا {SPEAKER_FEMALE}: ...

متن اخبار:
{source_text}
"""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction="تو یک نویسنده پادکست حرفه‌ای فارسی هستی.",
            temperature=0.7,
        ),
    )
    script = response.text
    logger.info(f"Script generated: {len(script)} chars, {len(script.splitlines())} lines")
    return script


# =============================================================================
# Render script to audio via Gemini Live API (native audio dialog)
# =============================================================================

async def render_podcast_audio(script, output_path, corrections=None):
    """Send each script turn to Gemini Live API and collect PCM audio."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set!")
        return False

    lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
    turns = []
    for line in lines:
        match = re.match(rf"^({SPEAKER_MALE}|{SPEAKER_FEMALE})\s*:\s*(.*)", line)
        if not match:
            continue
        speaker, text = match.groups()
        voice = VOICE_FARID if speaker == SPEAKER_MALE else VOICE_DILARA

        # Apply pronunciation corrections
        if corrections:
            for wrong, right in corrections.items():
                text = text.replace(wrong, right)

        turns.append((speaker, text, voice))

    logger.info(f"Rendering {len(turns)} turns via Gemini Live API...")

    all_pcm = bytearray()

    for i, (speaker, text, voice) in enumerate(turns):
        logger.info(f"Turn {i+1}/{len(turns)}: {speaker}: {text[:60]}...")

        try:
            client = genai.Client(api_key=api_key)
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
                system_instruction=(
                    f"You are {speaker}. Speak in natural contemporary Iranian Persian. "
                    "Deliver the text as warm, natural human speech. "
                    "Say each sentence once at a comfortable pace."
                ),
                temperature=0.7,
            )

            async with client.aio.live.connect(model=MODEL, config=config) as session:
                prompt = (
                    "Perform only the exact text inside <READ>. Preserve every word, but deliver "
                    "it as warm, natural human speech with varied emphasis, comfortable phrasing, "
                    "and unhurried articulation. Say each sentence once. Stop immediately after the "
                    f"final word and produce only audible speech.\n\n<READ>\n{text}\n</READ>"
                )

                await session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": prompt}]}]
                )

                pcm = bytearray()
                async for message in session.receive():
                    # Extract audio
                    server_content = getattr(message, "server_content", None)
                    model_turn = getattr(server_content, "model_turn", None) if server_content else None
                    for part in getattr(model_turn, "parts", None) or []:
                        inline = getattr(part, "inline_data", None)
                        data = getattr(inline, "data", None) if inline else None
                        if data:
                            pcm.extend(data)

                    # Also check direct data attribute
                    if not pcm and getattr(message, "data", None):
                        pcm.extend(message.data)

                    if server_content and (
                        getattr(server_content, "turn_complete", False)
                        or getattr(server_content, "generation_complete", False)
                    ):
                        break

                if pcm:
                    all_pcm.extend(pcm)
                    logger.info(f"  Got {len(pcm)} bytes PCM ({len(pcm)/(SAMPLE_RATE*2):.1f}s)")
                else:
                    logger.warning(f"  No audio for turn {i+1}")

        except Exception as e:
            logger.error(f"Error on turn {i+1}: {e}")
            continue

        await asyncio.sleep(1)  # Rate limit

    if not all_pcm:
        logger.error("No audio generated!")
        return False

    # Write WAV file
    with wave.open(output_path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(all_pcm))

    duration = len(all_pcm) / (SAMPLE_RATE * 2)
    logger.info(f"Podcast saved: {output_path} ({duration:.1f}s)")
    return True


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
        logger.info(f"Fetching messages from {len(channels)} channels...")
        since_date = (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        messages = []
        for ch in channels:
            username = ch.lstrip("@") if isinstance(ch, str) else ch.get("username", "").lstrip("@")
            msgs = await fetch_messages_from_channel(client, username, since_date)
            messages.extend(msgs)
            await asyncio.sleep(2)
        await client.disconnect()
        logger.info(f"Total messages fetched: {len(messages)}")

        if not messages:
            logger.warning("No messages found. Nothing to podcast.")
            return

        filtered = filter_messages(messages, config)
        if not filtered:
            logger.warning("No messages after filtering.")
            return

        source_text, podcast_date, total_msgs, active_channels = build_source_text(filtered)
        logger.info(f"Source text built: {total_msgs} msgs from {active_channels} channels, date={podcast_date}")

        # Step 1: Gemini generates podcast script
        logger.info("Generating podcast script via Gemini API...")
        script = generate_podcast_script(source_text, podcast_date)
        if not script:
            logger.error("Script generation failed!")
            return

        # Step 2: Gemini Live renders audio
        os.makedirs("output", exist_ok=True)
        date_slug = podcast_date.replace(" ", "_")
        output_path = f"output/podcast_{date_slug}.wav"
        logger.info("Rendering podcast audio via Gemini Live API...")
        success = await render_podcast_audio(script, output_path,
            corrections=config.get("pronunciation_corrections", {}))

        if not success:
            logger.error("Audio generation failed!")
            return

        # Step 3: Send to Telegram
        logger.info("Sending to Telegram...")
        caption = f"🎙️ پادکست کوهنامه\n📅 {podcast_date}\n📊 {total_msgs} پیام از {active_channels} کانال"
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
    logger.info("Starting Koohnameh Podcast Bot v5 (Gemini Native Audio)...")
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
