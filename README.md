# MakeSweet Slack Bot 🎬

A Slack bot that generates fun animated GIFs when you react to images with specific emojis!

## How It Works

1. Someone posts an image in Slack
2. React to it with a supported emoji
3. The bot generates an animated GIF using [MakeSweet](https://makesweet.com/) and replies in a thread

## Supported Emojis

| Emoji | Template | Description |
|-------|----------|-------------|
| 💖 ❤️ 💕 💗 💞 💘 | Heart Locket | Opens a heart locket to reveal your image |
| 🏙️ 🌇 🌆 | Billboard | Your image on a city billboard |
| 🏁 🏳️ 🚩 | Flag | Your image waving as a flag |
| 🐻 🧸 | Flying Bear | A bear flies in with your image |
| 🔌 💻 🖥️ | Circuit Board | Your image on a circuit board |
| 🪆 | Nesting Doll | Your image on a nesting doll |

## Setup

### 1. Create the Slack App

1. Go to [api.slack.com/apps?new_app=1](https://api.slack.com/apps?new_app=1)
2. Choose **From a manifest**
3. Select your workspace
4. Paste the contents of `manifest.yml`
5. Click **Create**
6. Click **Install to Workspace** and authorize

### 2. Get Your Tokens

- **Bot Token** (`SLACK_BOT_TOKEN`): Go to **OAuth & Permissions** → copy the **Bot User OAuth Token** (starts with `xoxb-`)
- **App Token** (`SLACK_APP_TOKEN`): Go to **Basic Information** → scroll to **App-Level Tokens** → click **Generate Token and Scopes** → add the `connections:write` scope → copy the token (starts with `xapp-`)

### 3. Deploy

#### On Render

1. Fork this repo
2. Click **New Web Service** on [render.com](https://render.com)
3. Connect your fork
4. Set environment variables:
   - `SLACK_BOT_TOKEN` = your bot token
   - `SLACK_APP_TOKEN` = your app-level token
   - `MAKESWEET_URL` = your MakeSweet server URL (e.g., `https://makesweet-server.onrender.com`)
5. Deploy!

#### Locally

```bash
export SLACK_BOT_TOKEN=xoxb-your-token
export SLACK_APP_TOKEN=xapp-your-token
export MAKESWEET_URL=https://makesweet-server.onrender.com
pip install -r requirements.txt
python bot.py
```

## Requirements

- A running [makesweet-server](https://github.com/Maheshivara/makesweet-server) instance
- Python 3.11+

## Note

On Render's free tier, the service may spin down after 15 minutes of inactivity. The first reaction after idle may take ~30 seconds to wake up.
