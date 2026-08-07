#!/usr/bin/env python3
"""
Podcast Bot - Fetches content from sources and generates Persian podcasts.
Uses Podcastfy for audio generation.
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


def fetch_feeds(feed_urls, max_per_feed=5):
    """Fetch RSS feeds and return entries."""
    all_entries = []
    
    for url in feed_urls:
        logger.info(f"Fetching: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries[:max_per_feed]:
                    # Get clean text content
                    summary = entry.get("summary", entry.get("description", ""))
                    clean_summary = BeautifulSoup(summary, "html.parser").get_text()
                    
                    all_entries.append({
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "content": clean_summary[:2000],
                        "published": entry.get("published", ""),
                        "source": url,
                        "feed_title": feed.feed.get("title", url),
                    })
                logger.info(f"  Found {len(feed.entries)} entries")
        except Exception as e:
            logger.error(f"  Error: {e}")
    
    return all_entries


def fetch_webpage(url):
    """Fetch and extract text content from a webpage."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Remove scripts and styles
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text
        text = soup.get_text()
        
        # Clean up
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = " ".join(chunk for chunk in chunks if chunk)
        
        return text[:5000]
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None


def prepare_content_for_podcast(entries, config):
    """Prepare content from entries for podcast generation."""
    content_parts = []
    
    for entry in entries[:5]:  # Limit to 5 entries
        title = entry.get("title", "")
        content = entry.get("content", "")
        source = entry.get("feed_title", "")
        
        if content:
            content_parts.append(f"مقاله: {title}\nمنبع: {source}\n\n{content[:1500]}\n\n---\n")
    
    return "\n".join(content_parts)


def generate_podcast(content, output_path, config):
    """Generate podcast using Podcastfy."""
    try:
        # Import podcastfy
        from podcastfy.client import generate_podcast
        
        # Configure for Persian
        conversation_config = {
            "system_prompt": "شما دو میزبان پادکست هستید که به زبان فارسی صحبت می‌کنید. مطالب را به صورت ساده و روان توضیح دهید.",
            "style": "conversational",
            "language": "fa",
        }
        
        # Generate podcast
        logger.info("Generating podcast...")
        result = generate_podcast(
            text_content=content,
            output_path=output_path,
            longform=True,
            conversation_config=conversation_config,
        )
        
        logger.info(f"Podcast generated: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error generating podcast: {e}")
        return False


def send_telegram_audio(bot_token, chat_id, audio_path, caption=""):
    """Send audio file to Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    
    try:
        with open(audio_path, "rb") as audio:
            files = {"audio": audio}
            data = {
                "chat_id": chat_id,
                "caption": caption[:1024],
                "title": "پادکست روزانه",
            }
            resp = requests.post(url, data=data, files=files, timeout=60)
            
            if resp.status_code == 200:
                logger.info("Audio sent to Telegram successfully")
                return True
            else:
                logger.error(f"Telegram error: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def send_telegram_message(bot_token, chat_id, text):
    """Send text message to Telegram."""
    url = f"https://api.telegram.org/bot{chat_id}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def main():
    """Main function."""
    logger.info("=" * 60)
    logger.info("PODCAST BOT - Starting daily generation")
    logger.info("=" * 60)
    
    # Load config
    config = load_config()
    feed_urls = config.get("feeds", [])
    
    # Fetch content
    logger.info("\n📡 Fetching content...")
    entries = fetch_feeds(feed_urls, max_per_feed=config.get("max_per_feed", 5))
    logger.info(f"Total entries: {len(entries)}")
    
    if not entries:
        logger.warning("No entries found")
        return
    
    # Prepare content
    logger.info("\n📝 Preparing content...")
    content = prepare_content_for_podcast(entries, config)
    logger.info(f"Content length: {len(content)} chars")
    
    # Generate podcast
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"podcast_{timestamp}.mp3")
    
    logger.info("\n🎙️ Generating podcast...")
    success = generate_podcast(content, output_path, config)
    
    if not success or not os.path.exists(output_path):
        logger.error("Failed to generate podcast")
        return
    
    # Get file size
    file_size = os.path.getsize(output_path)
    logger.info(f"Podcast size: {file_size / 1024 / 1024:.2f} MB")
    
    # Send to Telegram
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if bot_token and chat_id:
        logger.info("\n📤 Sending to Telegram...")
        caption = f"🎙️ پادکست روزانه\n📅 {datetime.utcnow().strftime('%Y-%m-%d')}\n📝 {len(entries)} مقاله"
        send_telegram_audio(bot_token, chat_id, output_path, caption)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    
    # Save results
    results = {
        "date": datetime.utcnow().isoformat(),
        "entries_count": len(entries),
        "content_length": len(content),
        "output_file": output_path,
        "file_size_mb": file_size / 1024 / 1024,
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n✅ Done! Podcast saved to: {output_path}")


if __name__ == "__main__":
    main()
