# 🎙️ Koohnameh Podcast Bot

Daily Persian podcast generator that reads mountaineering news from Telegram channels and produces audio via Google NotebookLM.

## Features

- 📡 Reads 22+ Iranian mountaineering Telegram channels
- 🔍 Smart content filtering (excludes class announcements, tours, nature trips)
- 🎙️ Generates Persian podcasts via NotebookLM Audio Overview
- 📱 Sends audio to Telegram automatically
- ⏰ Runs daily at 21:30 Iran time via GitHub Actions

## Setup

### 1. Local Setup (one-time)

Install notebooklm-py and login to get auth tokens:

```bash
pip install "notebooklm-py[headless]"
notebooklm login --browser msedge --master-token --account YOUR_EMAIL@gmail.com
```

This creates two files:
- `~/.notebooklm/profiles/default/master_token.json`
- `~/.notebooklm/profiles/default/storage_state.json`

### 2. Telegram API Keys

| Service | URL | Purpose |
|---------|-----|---------|
| Telegram Bot | [@BotFather](https://t.me/BotFather) | Send audio |
| Telegram API | [my.telegram.org](https://my.telegram.org) | Read channels |

### 3. Create GitHub Secrets

Go to Settings → Secrets and variables → Actions:

| Secret Name | Value |
|-------------|-------|
| `TELEGRAM_API_ID` | From my.telegram.org |
| `TELEGRAM_API_HASH` | From my.telegram.org |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Target chat/group ID |
| `NOTEBOOKLM_MASTER_TOKEN` | Content of `master_token.json` |
| `NOTEBOOKLM_AUTH_JSON` | Content of `storage_state.json` |

### 4. Enable GitHub Actions

Go to Actions → Enable workflow

## How It Works

```
Every day at 21:30 Iran time:
    ↓
1. Read messages from 22+ Telegram channels
    ↓
2. Filter content (exclude ads, announcements)
    ↓
3. Create NotebookLM notebook with content
    ↓
4. Generate Persian audio overview (podcast)
    ↓
5. Download audio and send to Telegram
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

## Project Structure

```
podcast-bot/
├── main.py                  # Main script
├── config.yaml              # Channel list & filters
├── requirements.txt         # Dependencies
├── .github/
│   └── workflows/
│       └── daily.yml       # GitHub Actions workflow
└── output/                  # Generated podcasts
```

## Auth Refresh

The master token auto-refreshes cookies. If auth fails, re-login locally:

```bash
notebooklm login --browser msedge --master-token --account YOUR_EMAIL@gmail.com
```

Then update the GitHub secrets with new token files.
