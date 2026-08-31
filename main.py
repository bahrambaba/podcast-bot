# Koohnameh Podcast Bot v5
# Fetches news from 86 Telegram channels → Gemini script → Gemini Native Audio → Telegram channel

import os
import re
import asyncio
import logging
import json
import wave
import time
import jdatetime
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Gemini Native Audio Dialog config
MODEL_AUDIO = "models/gemini-2.5-flash-native-audio-preview-12-2025"
SAMPLE_RATE = 24000
JALALI_MONTHS = [
    "ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
    "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"
]

# Voice config
VOICE_FARID = "Charon"       # Informative male
VOICE_DILARA = "Aoede"      # Breezy female
SPEAKER_MALE = "فرشید"
SPEAKER_FEMALE = "پریسا"


# =============================================================================
# Load config
# =============================================================================

def load_config():
    import yaml
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# Fetch messages from a single channel
# =============================================================================

async def fetch_messages_from_channel(client, channel_username, since_date):
    try:
        entity = await client.get_entity(channel_username)
        messages = []
        async for message in client.iter_messages(entity, limit=50):
            if message.date.replace(tzinfo=None) >= since_date:
                text = message.text or ""
                messages.append({
                    "text": text,
                    "channel": channel_username,
                    "date": message.date.isoformat(),
                    "has_media": message.media is not None,
                    "has_text": bool(text),
                })
        return messages
    except Exception as e:
        logger.error(f"Error fetching @{channel_username}: {e}")
        return []


# =============================================================================
# Filter messages
# =============================================================================

def filter_messages(messages, config):
    filters = config.get("filters", {})
    exclude_keywords = filters.get("exclude_keywords", [])
    min_caption_length = filters.get("min_caption_length", 50)
    priority_channels = set(config.get("priority_channels", []))
    filtered = []
    seen_texts = set()
    for msg in messages:
        channel = msg.get("channel", "")
        is_priority = channel in priority_channels
        text = msg.get("text", "").strip()
        if not text:
            continue
        # Priority channels bypass min length and media filters
        if not is_priority:
            if len(text) < min_caption_length:
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
    return filtered


# =============================================================================
# Build source text
# =============================================================================

def build_source_text(filtered_messages, priority_channels=None, channel_names=None):
    today_jalali = jdatetime.datetime.now()
    yesterday_jalali = today_jalali - jdatetime.timedelta(days=1)
    yesterday_date = f"{yesterday_jalali.day} {JALALI_MONTHS[yesterday_jalali.month - 1]} {yesterday_jalali.year}"
    podcast_date = f"{today_jalali.day} {JALALI_MONTHS[today_jalali.month - 1]} {today_jalali.year}"

    priority = set(priority_channels or [])
    names = channel_names or {}
    channels = {}
    for msg in filtered_messages:
        ch = msg.get("channel", "نامشخص")
        channels.setdefault(ch, []).append(msg.get("text", "")[:500])

    total_msgs = len(filtered_messages)
    active_channels = len(channels)

    text_parts = [f"آمار: {total_msgs} پیام از {active_channels} کانال فعال.\n"]
    for ch_name, msgs in channels.items():
        friendly = names.get(f"@{ch_name}", ch_name)
        tag = " ⭐ اولویت" if f"@{ch_name}" in priority else ""
        text_parts.append(f"\nکانال {friendly}{tag}:")
        for m in msgs[:5]:
            text_parts.append(f"- {m}")

    return "\n".join(text_parts), podcast_date, total_msgs, active_channels


# =============================================================================
# Gemini script generation
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
- کانال‌هایی که نشان ⭐ اولویت دارند حتماً و با جزئیات بیشتر پوشش داده شوند.
- شروع دقیقاً با:
{SPEAKER_MALE}: سلام و درود خدمت شنوندگان عزیز پادکست کوهنامه.
{SPEAKER_FEMALE}: امروز تاریخ {podcast_date} هست و در تحریریه سایت کوهنامه با خلاصه‌ای از اخبار و نوشته‌های کوهنوردی که دیروز در فضای مجازی منتشر شده در خدمتتون هستیم.
{SPEAKER_MALE}: خوب بریم با هم مروری داشته باشیم بر روی مطالب کانال‌های فعال دیروز.

- پایان دقیقاً با:
{SPEAKER_FEMALE}: امیدوارم از شنیدن این پادکست لذت برده باشید.
{SPEAKER_MALE}: هر روز منتظر انتشار پادکست‌های صوتی روزانه از کوهنامه باشید.
{SPEAKER_FEMALE}: تا پادکست بعدی، خدا نگهدارتون باشه.

- حداکثر ۲۵ خط دیالوگ
- هر خط با فرمت: نام‌سخنران: متن
- فقط از نام‌های {SPEAKER_MALE} و {SPEAKER_FEMALE} استفاده کن
- از emoji استفاده نکن
- اعداد فارسی باشند

متن اخبار:
{source_text}"""

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            return response.text
        except Exception as e:
            logger.warning(f"Script generation attempt {attempt+1} failed: {e}")
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
    logger.error("All script generation attempts failed")
    return None


# =============================================================================
# Render script to audio via Gemini Live API
# =============================================================================

async def render_podcast_audio(script, output_path, corrections=None):
    """Send each script turn to Gemini Live API and collect PCM audio."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set!")
        return False

    from google import genai
    from google.genai import types

    lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
    turns = []
    for line in lines:
        match = re.match(rf"^({SPEAKER_MALE}|{SPEAKER_FEMALE})\s*:\s*(.*)", line)
        if not match:
            continue
        speaker, text = match.groups()
        voice = VOICE_FARID if speaker == SPEAKER_MALE else VOICE_DILARA

        # Apply pronunciation corrections (longest first to avoid partial matches)
        if corrections:
            for wrong, right in sorted(corrections.items(), key=lambda x: len(x[0]), reverse=True):
                text = text.replace(wrong, right)

        turns.append((speaker, text, voice))

    if not turns:
        logger.error("No valid turns found in script!")
        return False

    logger.info(f"Rendering {len(turns)} turns to audio...")

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
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            )

            async with client.aio.live.connect(model=MODEL_AUDIO, config=config) as session:
                prompt = f"Perform only the exact text inside <READ>. Prepend a brief appropriate greeting. Follow all instructions inside <INSTRUCTIONS>.\n<INSTRUCTIONS>Speak naturally like a real podcast host. Use natural pauses, warmth, and personality.</INSTRUCTIONS>\n<READ>{text}</READ>"

                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
                    turn_complete=True,
                )

                audio_buffer = bytearray()
                async for chunk in session.receive():
                    if chunk.server_content is not None:
                        if chunk.server_content.model_turn is not None:
                            for part in chunk.server_content.model_turn.parts:
                                if part.inline_data is not None:
                                    audio_buffer.extend(part.inline_data.data)
                        if chunk.server_content.turn_complete:
                            break

                if audio_buffer:
                    all_pcm.extend(audio_buffer)
                    logger.info(f"  Got {len(audio_buffer)} bytes PCM audio")
                else:
                    logger.warning(f"  No audio for turn {i+1}")

        except Exception as e:
            logger.error(f"  Error on turn {i+1}: {e}")
            continue

    if not all_pcm:
        logger.error("No audio collected!")
        return False

    # Save as WAV
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(all_pcm))

    logger.info(f"Saved {len(all_pcm)} bytes PCM to {output_path}")
    return True


# =============================================================================
# Send to Telegram
# =============================================================================

def send_to_telegram(audio_path, title, caption):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set!")
        return

    import requests

    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    with open(audio_path, "rb") as f:
        files = {"audio": f}
        data = {
            "chat_id": chat_id,
            "title": title,
            "caption": caption[:1024],
            "parse_mode": "HTML",
        }
        resp = requests.post(url, files=files, data=data, timeout=120)
        if resp.status_code == 200:
            logger.info("Audio sent to Telegram successfully")
        else:
            logger.error(f"Failed to send: {resp.status_code} {resp.text}")


# =============================================================================
# Main
# =============================================================================

async def async_main():
    config = load_config()
    channels = config.get("channels", [])

    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH not set!")
        return

    from telethon import TelegramClient
    client = TelegramClient("bot_session", int(api_id), api_hash)
    await client.start(bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    try:
        logger.info(f"Fetching messages from {len(channels)} channels...")
        since_date = datetime.utcnow() - timedelta(hours=24)
        messages = []
        for ch in channels:
            username = ch.lstrip("@") if isinstance(ch, str) else ch.get("username", "").lstrip("@")
            msgs = await fetch_messages_from_channel(client, username, since_date)
            messages.extend(msgs)
            await asyncio.sleep(1)

        logger.info(f"Total messages fetched: {len(messages)}")

        # Filter
        filtered = filter_messages(messages, config)
        logger.info(f"Messages after filtering: {len(filtered)}")

        if not filtered:
            logger.warning("No messages after filtering.")
            return

        source_text, podcast_date, total_msgs, active_channels = build_source_text(
            filtered, priority_channels=config.get("priority_channels", []),
            channel_names=config.get("channel_names", {}))
        logger.info(f"Source text built: {total_msgs} msgs from {active_channels} channels, date={podcast_date}")

        # Step 1: Gemini generates podcast script
        logger.info("Generating podcast script...")
        script = generate_podcast_script(source_text, podcast_date)
        if not script:
            logger.error("Failed to generate script!")
            return
        logger.info(f"Script generated ({len(script)} chars)")

        # Step 2: Render audio via Gemini Native Audio Dialog
        output_path = "output/podcast.wav"
        success = await render_podcast_audio(script, output_path,
            corrections=config.get("pronunciation_corrections", {}))
        if not success:
            logger.error("Failed to render audio!")
            return

        # Step 3: Send to Telegram
        logger.info("Sending to Telegram...")
        title = f"پادکست کوهنامه {podcast_date}"
        caption = (
            f"🎙 پادکست روز \"{podcast_date}\" کوهنامه -تهیه شده توسط هوش مصنوعی ( توجه: ایرادات، تلفظ اسامی و  تلفظ نام ها خطای ذاتی هوش مصنوعی است و کوهنامه نقشی در آن ندارد.) این پادکست به صورت روزانه از بین کانال های فعال تلگرامی تهیه می شود.\n"
            f"📅 {podcast_date}\n"
            f"────────────\n"
            f"🌐 کوهنامه | اخبار کوهنوردی\n"
            f"📍 www.koohnameh.ir\n"
            f"📢 @koohnameh"
        )
        send_to_telegram(output_path, title, caption)

        logger.info("Done!")

    finally:
        await client.disconnect()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    from google import genai
    main()
