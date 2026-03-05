# MakeSweet Slack Bot 🎬

A Slack bot that generates animated GIFs when you react to images with emojis. Powered by [MakeSweet](https://makesweet.com/) and real-time Socket Mode.

## How It Works

1. Someone posts an image in Slack
2. React to it with a supported emoji
3. The bot generates an animated GIF and replies in a thread ✨

**Don't know which emojis work?** Reply `how` to any image and the bot will list them.

## Supported Reactions

| Emoji | Template | Image Slots |
|-------|----------|-------------|
| 💖 ❤️ 💕 💗 💞 💘 | Heart Locket | Posted image + reactor's avatar |
| 🏙️ 🌇 🌆 | Billboard | Posted image |
| 🏁 🏳️ 🚩 | Flag | Posted image |
| 🐻 🧸 | Flying Bear | Posted image |
| 🪆 | Nesting Doll | Posted image + reactor's avatar + poster's avatar |

## Smart Multi-Image Handling

Some templates have multiple image slots. Instead of duplicating the same image, the bot gets creative:

**💖 Heart Locket** (2 slots)
- Left: the posted image
- Right: the **reactor's** Slack profile picture

**🪆 Nesting Doll** (3 slots)
- Left: the posted image
- Mid: the **reactor's** avatar
- Right: the **poster's** avatar

If the message contains multiple images, those take priority over avatars. The bot always falls back gracefully if it can't find enough unique images.

## Setup

### 1. Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps?new_app=1) → **Create New App** → **From a manifest**
2. Select your workspace
3. Paste the manifest below (JSON):

```json
{
  "display_information": {
    "name": "MakeSweet GIF Bot",
    "description": "React to images with emojis to generate fun animated GIFs!",
    "background_color": "#FF6B6B"
  },
  "features": {
    "bot_user": {
      "display_name": "MakeSweet",
      "always_online": true
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "reactions:read",
        "channels:history",
        "groups:history",
        "im:history",
        "mpim:history",
        "files:read",
        "files:write",
        "chat:write",
        "users:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "message.channels",
        "message.groups",
        "reaction_added"
      ]
    },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```

4. Click **Create** → **Install to Workspace**

### 2. Get Your Tokens

| Token | Where to Find |
|-------|---------------|
| **Bot Token** (`xoxb-...`) | OAuth & Permissions → Bot User OAuth Token |
| **App Token** (`xapp-...`) | Basic Information → App-Level Tokens → Generate (add `connections:write` scope) |

### 3. Deploy

#### Render (recommended)

Set these environment variables on a new Web Service:

| Variable | Value |
|----------|-------|
| `SLACK_BOT_TOKEN` | Your `xoxb-...` token |
| `SLACK_APP_TOKEN` | Your `xapp-...` token |
| `MAKESWEET_URL` | URL of your MakeSweet server (e.g. `https://makesweet-server.onrender.com`) |

#### Locally

```bash
export SLACK_BOT_TOKEN=xoxb-your-token
export SLACK_APP_TOKEN=xapp-your-token
export MAKESWEET_URL=https://makesweet-server.onrender.com
pip install -r requirements.txt
python bot.py
```

## Requirements

- Python 3.11+
- A running [makesweet-server](https://github.com/guitarbeat/makesweet-server) instance

## Architecture

```
Slack ←→ Socket Mode ←→ bot.py ←→ makesweet-server ←→ GIF
         (real-time)              (HTTP POST)
```

The bot uses **Socket Mode** — no public URL or webhook needed. It connects outbound to Slack's servers, so it works behind firewalls and on platforms like Render's free tier.

## Note

On Render's free tier, services spin down after 15 minutes of inactivity. The first reaction after idle may take ~30 seconds while the bot wakes up.
