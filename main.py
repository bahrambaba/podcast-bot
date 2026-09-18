#!/usr/bin/env python3
"""
Koohnameh Podcast Bot v5
Gemini 2.5 Flash Native Audio Dialog for direct audio generation.
No edge-tts, no NotebookLM. Native audio from Gemini Live API.
"""

import asyncio
import json
import os
import random
import re
import wave
import yaml
import logging
import requests
from datetime import datetime, timedelta
import jdatetime
from google import genai
from google.genai import types
from pydub import AudioSegment

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
    logger.info(f"Filtered {len(messages)} -> {len(filtered)} messages (deduped)")
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
# Generate podcast script via Gemini text model
# =============================================================================

def generate_podcast_script(source_text, podcast_date):
    """Use Gemini to turn raw news text into a podcast dialogue script."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set!")
        return None

    client = genai.Client(api_key=api_key)

    prompt = f"""
# نقش
تو نویسنده‌ی حرفه‌ای دیالوگ پادکست خبری هستی، متخصص تبدیل خبرهای خام به گفتگوی رادیویی طبیعی و پرانرژی بین دو مجری.

# ورودی
متن اخبار زیر شامل چند خبر کوهنوردی از کانال‌های مختلف است. کانال‌هایی که با نشان ⭐ مشخص شده‌اند، اخبار اولویت‌دار محسوب می‌شوند.

متن اخبار:
{source_text}

# مجری‌ها
- {SPEAKER_MALE} (مذکر)
- {SPEAKER_FEMALE} (مونث)

# لحن
گرم، صمیمی، پرانرژی، شبیه یک برنامه‌ی صبحگاهی رادیویی. مجری‌ها با هم راحت صحبت می‌کنند، گاهی شوخی سبک یا تعجب طبیعی نشان می‌دهند، و از تکرار عبارات یکسان در طول برنامه خودداری می‌کنند.

# ساختار خروجی

## بدنه (برای هر خبر این الگو را رعایت کن)
۱. یک مجری خبر را با کلمات خودش باز می‌کند (نه ترجمه یا کپی مستقیم متن منبع).
۲. همان مجری ۲-۳ جمله‌ی دیگر جزئیات را توضیح می‌دهد (چه اتفاقی افتاده، چه کسی، چرا مهم است).
۳. مجری دوم با یک واکنش طبیعی (سؤال، تعجب، مقایسه، یا تحلیل کوتاه) وارد می‌شود — حداقل ۲ جمله.
۴. در صورت نیاز، مجری اول با یک جمع‌بندی کوتاه (۱ جمله) خبر را می‌بندد.
۵. انتقال به خبر بعدی با عبارتی متفاوت از خبرهای قبلی انجام شود (از تکرار عین یک جمله‌ی انتقالی در کل پادکست خودداری کن).

قوانین اختصاصی محتوا:
- اخبار کانال‌های ⭐ باید نسبت به بقیه با جزئیات بیشتر (حداقل ۵-۶ جمله‌ی مجموع بین دو مجری) و با یک تحلیل کوتاه اضافه پوشش داده شوند.
- اخبار غیر ⭐ در حد ۳-۴ جمله‌ی مجموع کافی است؛ آن‌ها را مصنوعی طولانی نکن.
- ترتیب روایت اخبار را از متن منبع حفظ کن مگر اینکه منطقاً نیاز به تغییر باشد.
- هیچ خبری را حذف نکن؛ اگر خبری بسیار کوتاه یا کم‌اهمیت است، آن را در ۱-۲ جمله رد کن، نه با پرکردن مصنوعی.

# قوانین سخت‌گیرانه‌ی خروجی
- فقط و فقط دیالوگ خروجی بده؛ هیچ توضیح، عنوان، یادداشت، یا خلاصه‌ی اضافه ننویس.
- هیچ نشانه‌ی مارک‌داون (ستاره، هشتگ، خط تیره، براکت) در خروجی نباشد.
- هر خط دقیقاً با یکی از این دو فرمت شروع شود:
{SPEAKER_MALE}: ...
{SPEAKER_FEMALE}: ...
- از متن منبع کپی مستقیم نکن؛ همه‌چیز را با زبان طبیعی گفتاری بازنویسی کن.
- طول کل دیالوگ متناسب با تعداد اخبار موجود در متن منبع باشد؛ اگر اخبار کم بود، دیالوگ را با پرحرفی مصنوعی طولانی نکن.
- **مهم:** متن آغاز و پایان را ننویس — این دو بخش جداگانه تولید و به ابتدا/انتها اضافه میشوند. خروجی فقط بدنه باشد (خبرها)، بدون مقدمه و بدون جمعبندی.
"""

    # Retry with backoff for 503/overload errors
    import time
    MAX_ROUNDS = 3  # 3 rounds x 5 attempts = 15 total attempts
    ROUND_WAIT = 3600  # 1 hour between rounds

    for round_num in range(MAX_ROUNDS):
        if round_num > 0:
            logger.warning(f"All 5 attempts failed. Waiting {ROUND_WAIT}s (1 hour) before round {round_num+1}...")
            time.sleep(ROUND_WAIT)

        for attempt in range(5):
            try:
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
            except Exception as e:
                wait = 120 + (60 * attempt)  # 120, 180, 240, 300, 360
                logger.warning(f"Script generation attempt {attempt+1}/5 (round {round_num+1}/{MAX_ROUNDS}) failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)

    logger.error("Script generation failed after all rounds!")
    return None


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

        # Apply pronunciation corrections (longest first to avoid partial matches)
        if corrections:
            for wrong, right in sorted(corrections.items(), key=lambda x: len(x[0]), reverse=True):
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

def send_to_telegram(audio_path, title, caption):
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
            "title": title,
            "performer": "کوهنامه",
        }
        resp = requests.post(url, files=files, data=data)
        if resp.status_code == 200:
            logger.info("Audio sent to Telegram successfully")
            return True
        logger.error(f"Telegram error: {resp.text}")
        return False


# =============================================================================
# Intro/Outro Audio Generation & Music Mixing
# =============================================================================

INTRO_MUSIC_DIR = "assets/intro_music"
OUTRO_MUSIC_DIR = "assets/outro_music"
FADE_DURATION_MS = 2000  # 2 seconds fade in/out


def get_random_music_file(music_dir):
    """Get random music file from directory, or None if empty/missing."""
    if not os.path.isdir(music_dir):
        return None
    files = [f for f in os.listdir(music_dir) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))]
    if not files:
        return None
    return os.path.join(music_dir, random.choice(files))


def build_intro_text(podcast_date, yesterday_date):
    return (
        f"{SPEAKER_MALE}: سلام و درود خدمت شنوندگان عزیز پادکست کوهنامه. "
        f"امروز {podcast_date} هست و در تحریریه سایت کوهنامه با خلاصه‌ای از اخبار "
        f"و نوشته‌های کوهنوردی که دیروز در فضای مجازی منتشر شده در خدمتتون هستیم. "
        f"خوب بریم با هم مروری داشته باشیم بر روی مطالب {yesterday_date}."
    )


def build_outro_text():
    return (
        f"{SPEAKER_FEMALE}: امیدوارم از شنیدن این پادکست لذت برده باشید. "
        f"هر روز منتظر انتشار پادکست‌های صوتی روزانه از کوهنامه باشید و پادکست‌های ما "
        f"را با دوستان کوهنورد خود در گروه ها به اشتراک بگذارید. "
        f"{SPEAKER_MALE}: تا پادکست صبحگاهی فردا، خدا نگهدارتون باشه."
    )


async def generate_tts_audio(text, output_wav, voice):
    """Generate TTS audio for a single text block using Gemini Live API."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set!")
        return False

    # Speaker labels are metadata, not words to pronounce — strip ALL of them
    # (intro/outro blocks may contain multiple label switches mid-text).
    text = re.sub(rf"\s*({SPEAKER_MALE}|{SPEAKER_FEMALE})\s*:\s*", "", text).strip()
    if not text:
        logger.error("Nothing left to speak after stripping speaker labels!")
        return False

    client = genai.Client(api_key=api_key)
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
        system_instruction=(
            "Speak in natural contemporary Iranian Persian. "
            "Deliver the text as warm, natural human speech. "
            "Say each sentence once at a comfortable pace."
        ),
        temperature=0.7,
    )

    try:
        async with client.aio.live.connect(model=MODEL, config=live_config) as session:
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
                server_content = getattr(message, "server_content", None)
                model_turn = getattr(server_content, "model_turn", None) if server_content else None
                for part in getattr(model_turn, "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    data = getattr(inline, "data", None) if inline else None
                    if data:
                        pcm.extend(data)
                if not pcm and getattr(message, "data", None):
                    pcm.extend(message.data)
                if server_content and (
                    getattr(server_content, "turn_complete", False)
                    or getattr(server_content, "generation_complete", False)
                ):
                    break

        if not pcm:
            logger.error("No audio generated for TTS")
            return False

        with wave.open(output_wav, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(bytes(pcm))

        logger.info(f"TTS WAV saved: {output_wav} ({len(pcm)/(SAMPLE_RATE*2):.1f}s)")
        return True
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return False


def mix_audio_with_music(speech_wav, output_wav, music_path):
    """Append one complete music track AFTER speech, with no overlap."""
    speech = AudioSegment.from_wav(speech_wav)
    if not music_path:
        logger.warning("Music folder is empty; exporting speech only")
        speech.export(output_wav, format="wav")
        return True

    music = AudioSegment.from_file(music_path)
    if len(music) == 0 or music.rms == 0:
        raise ValueError(f"Empty or silent music file: {music_path}")
    music = music.set_frame_rate(speech.frame_rate).set_channels(speech.channels).set_sample_width(speech.sample_width)
    # Standalone music: match speech loudness rather than apply background gain.
    target_dbfs = min(speech.dBFS, -16.0) if speech.rms else -20.0
    gain = min(target_dbfs - music.dBFS, -1.0 - music.max_dBFS)
    music = music.apply_gain(gain)
    fade_ms = min(FADE_DURATION_MS, len(music) // 2)
    if fade_ms:
        music = music.fade_in(fade_ms).fade_out(fade_ms)
    combined = speech + music
    combined.export(output_wav, format="wav")
    logger.info(f"Speech then standalone music: {music_path}; speech={len(speech)}ms, music={len(music)}ms, total={len(combined)}ms")
    return True


def clean_body_script(script):
    """Drop known opening/closing lines if the model ignores body-only instructions."""
    def normalized(text):
        return re.sub(r"[\s\u200c\u200d]+", "", text).replace("ي", "ی").replace("ك", "ک")

    markers = [normalized(text) for text in (
        "سلام و درود خدمت شنوندگان", "امیدوارم از شنیدن این پادکست", "خدا نگهدارتون باشه",
    )]
    kept = []
    for line in script.splitlines():
        match = re.match(rf"^\s*({SPEAKER_MALE}|{SPEAKER_FEMALE})\s*:\s*(.+)", line)
        if not match:
            continue
        if any(marker in normalized(match.group(2)) for marker in markers):
            logger.warning("Removed duplicate opening/closing line from body")
            continue
        kept.append(line.strip())
    if not kept:
        raise ValueError("No body dialogue remains after validation")
    return "\n".join(kept)


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
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    client = TelegramClient("user_session", api_id, api_hash)
    await client.start()
    try:
        logger.info(f"Fetching messages from {len(channels)} channels...")
        since_date = datetime.utcnow() - timedelta(hours=24)
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

        source_text, podcast_date, total_msgs, active_channels = build_source_text(
            filtered, priority_channels=config.get("priority_channels", []),
            channel_names=config.get("channel_names", {}))
        logger.info(f"Source text built: {total_msgs} msgs from {active_channels} channels, date={podcast_date}")

        # Step 1: Gemini generates podcast script
        logger.info("Generating podcast script via Gemini API...")
        script = generate_podcast_script(source_text, podcast_date)
        if not script:
            logger.error("Script generation failed!")
            return

        # Step 2: Render audio with intro/outro
        os.makedirs("output", exist_ok=True)
        date_slug = podcast_date.replace(" ", "_")
        wav_path = f"output/podcast_{date_slug}.wav"

        logger.info("Rendering podcast audio with intro/outro...")

        yesterday_jalali = jdatetime.datetime.now() - jdatetime.timedelta(days=1)
        yesterday_date = f"{yesterday_jalali.day} {JALALI_MONTHS[yesterday_jalali.month - 1]}"

        # Generate intro TTS + music
        intro_text = build_intro_text(podcast_date, yesterday_date)
        intro_tts_wav = f"output/intro_tts_{date_slug}.wav"
        intro_mixed_wav = f"output/intro_mixed_{date_slug}.wav"
        intro_music = get_random_music_file(INTRO_MUSIC_DIR)

        logger.info("Generating intro TTS...")
        if await generate_tts_audio(intro_text, intro_tts_wav, VOICE_FARID):
            logger.info(f"Mixing intro with music: {intro_music}")
            mix_audio_with_music(intro_tts_wav, intro_mixed_wav, intro_music)
        else:
            logger.error("Intro TTS failed")
            intro_mixed_wav = None

        # Generate outro TTS + music
        outro_text = build_outro_text()
        outro_tts_wav = f"output/outro_tts_{date_slug}.wav"
        outro_mixed_wav = f"output/outro_mixed_{date_slug}.wav"
        outro_music = get_random_music_file(OUTRO_MUSIC_DIR)

        logger.info("Generating outro TTS...")
        if await generate_tts_audio(outro_text, outro_tts_wav, VOICE_DILARA):
            logger.info(f"Mixing outro with music: {outro_music}")
            mix_audio_with_music(outro_tts_wav, outro_mixed_wav, outro_music)
        else:
            logger.error("Outro TTS failed")
            outro_mixed_wav = None

        # Generate body only; opening and closing have separate audio.
        script = clean_body_script(script)
        main_wav = f"output/main_{date_slug}.wav"
        logger.info("Rendering main content...")
        success = await render_podcast_audio(script, main_wav,
            corrections=config.get("pronunciation_corrections", {}))

        if not success:
            logger.error("Audio generation failed!")
            return

        # Combine all parts
        logger.info("Combining intro + main + outro...")
        combined = AudioSegment.empty()
        if intro_mixed_wav and os.path.exists(intro_mixed_wav):
            combined += AudioSegment.from_wav(intro_mixed_wav)
        combined += AudioSegment.from_wav(main_wav)
        if outro_mixed_wav and os.path.exists(outro_mixed_wav):
            combined += AudioSegment.from_wav(outro_mixed_wav)

        combined.export(wav_path, format="wav")
        logger.info(f"Final WAV saved: {wav_path} ({len(combined)/1000:.1f}s)")

        # Cleanup temp files
        for f in [intro_tts_wav, intro_mixed_wav, outro_tts_wav, outro_mixed_wav, main_wav]:
            if f and os.path.exists(f):
                os.remove(f)

        # Step 3: Send to Telegram
        logger.info("Sending to Telegram...")
        title = f"پادکست کوهنامه {podcast_date}"
        caption = (
            f"🎙 پادکست روز \"{podcast_date}\" کوهنامه -تهیه شده توسط هوش مصنوعی "
            f"( توجه: ایرادات، تلفظ اسامی و  تلفظ نام ها خطای ذاتی هوش مصنوعی است "
            f"و کوهنامه نقشی در آن ندارد.) این پادکست به صورت روزانه از بین کانال های فعال تلگرامی تهیه می شود.\n\n"
            f"📣 اگه این پادکست رو دوست داشتی، برای دوستان کوهنوردت هم بفرست تا اونا هم باخبر بشن!\n\n"
            f"🗻 از بین کانال‌های فعال تلگرامی، مهم‌ترین اخبار رو جمع کردیم تا تو از قافله عقب نمونی.\n\n"
            f"────────────\n"
            f"🌐 کوهنامه | اخبار کوهنوردی\n"
            f"📍 www.koohnameh.ir\n"
            f"📢 @koohnameh"
        )
        send_to_telegram(wav_path, title, caption)
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
