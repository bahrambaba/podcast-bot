# 🎙️ Persian Podcast Bot

Automatic podcast generator that fetches content from RSS feeds and generates Persian audio using AI.

## Features

- 📡 Fetches content from multiple RSS feeds
- 🤖 Uses AI to generate natural conversations
- 🎙️ Generates 15-20 minute Persian podcasts
- 📱 Sends audio to Telegram automatically
- ⏰ Runs daily via GitHub Actions

## Setup

### 1. Get Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create a new API key
3. Copy the key

### 2. Create GitHub Secrets

Go to your repo Settings → Secrets and variables → Actions:

| Secret Name | Value |
|-------------|-------|
| `GEMINI_API_KEY` | Your Gemini API key |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### 3. Enable GitHub Actions

1. Go to Actions tab in your repo
2. Click "Enable workflow"

## Usage

### Automatic (Daily)
The bot runs automatically every day at 6:00 UTC (9:30 Iran time).

### Manual
Go to Actions → Daily Podcast Generation → Run workflow

## Configuration

Edit `config.yaml` to:
- Add/remove RSS feeds
- Change podcast duration
- Modify language/style settings

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

## How It Works

1. **Fetch**: Reads RSS feeds for latest articles
2. **Prepare**: Extracts and cleans content
3. **Generate**: Creates Persian conversation podcast
4. **Send**: Uploads audio to Telegram group

## License

MIT
