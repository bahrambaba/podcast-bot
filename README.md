# 🎙️ Koohnameh Podcast Bot

Daily podcast generator that reads mountaineering news from Telegram channels and produces Persian audio summaries.

## Features

- 📡 Reads 22+ Iranian mountaineering Telegram channels
- 🔍 Smart content filtering (excludes class announcements, tours, nature trips)
- 🎙️ Generates 15-20 minute Persian podcasts
- 🤖 Uses Gemini AI for script writing and TTS
- 📱 Sends audio to Telegram automatically
- ⏰ Runs daily via GitHub Actions

## Setup

### 1. Get Required API Keys

| Service | URL | Purpose |
|---------|-----|---------|
| Gemini API | [aistudio.google.com](https://aistudio.google.com/apikey) | AI + TTS |
| Telegram Bot | [@BotFather](https://t.me/BotFather) | Send audio |
| Telegram API | [my.telegram.org](https://my.telegram.org) | Read channels |

### 2. Create GitHub Secrets

Go to Settings → Secrets and variables → Actions:

| Secret Name | Value |
|-------------|-------|
| `GEMINI_API_KEY` | Gemini API key |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Target chat/group ID |
| `TELEGRAM_API_ID` | From my.telegram.org |
| `TELEGRAM_API_HASH` | From my.telegram.org |

### 3. Enable GitHub Actions

Go to Actions → Enable workflow

## How It Works

```
Every day at 21:30 Iran time:
    ↓
1. Get channel list from Koohnameh
    ↓
2. Read messages from each channel
    ↓
3. Filter content (exclude ads, announcements)
    ↓
4. Generate podcast script with Gemini AI
    ↓
5. Convert to Persian audio (TTS)
    ↓
6. Send to Telegram group
```

## Content Filtering

The bot automatically excludes:
- ❌ Class/course announcements
- ❌ Tour/nature trip schedules
- ❌ Images/videos without captions
- ❌ Very short messages (< 20 chars)

## Configuration

Edit `config.yaml` to:
- Add/remove channels
- Change filter keywords
- Modify podcast templates

## Project Structure

```
podcast-bot/
├── main.py              # Main script
├── config.yaml          # Configuration
├── requirements.txt     # Dependencies
├── .github/
│   └── workflows/
│       └── daily.yml   # GitHub Actions
├── output/              # Generated podcasts
└── data/               # Results cache
```

## License

MIT
