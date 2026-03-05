import os
import io
import random
import logging
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from flask import Flask
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Slack app
app = App(token=os.environ["SLACK_BOT_TOKEN"])

MAKESWEET_URL = os.environ.get("MAKESWEET_URL", "https://makesweet-server.onrender.com")

# Emoji to MakeSweet template mapping
EMOJI_TEMPLATE_MAP = {
    # Heart Locket 💖
    "sparkling_heart": "heart-locket",
    "heart": "heart-locket",
    "hearts": "heart-locket",
    "heartpulse": "heart-locket",
    "revolving_hearts": "heart-locket",
    "two_hearts": "heart-locket",
    "heart_decoration": "heart-locket",
    # Billboard 🏙️
    "cityscape": "billboard",
    "city_sunrise": "billboard",
    "city_sunset": "billboard",
    # Flag 🏳️
    "checkered_flag": "flag",
    "waving_white_flag": "flag",
    "triangular_flag_on_post": "flag",
    "flag-white": "flag",
    # Flying Bear 🐻
    "bear": "flying-bear",
    "teddy_bear": "flying-bear",
    # Nesting Doll 🪆
    "nesting_dolls": "nesting-doll",
}

# Template -> form field configuration
TEMPLATE_FIELDS = {
    "heart-locket": ["image-left", "image-right"],
    "billboard": ["image"],
    "flag": ["image"],
    "flying-bear": ["image"],
    "nesting-doll": ["image-left", "image-mid", "image-right"],
}

# ============================================================
# 🎭 PERSONALITY - co-op house energy
# ============================================================

THINKING_MESSAGES = [
    "🎨 hold on, crafting something beautiful...",
    "🧪 mixing the pixels in the communal kitchen...",
    "🪄 one sec, the gif wizard is doing their thing...",
    "🫧 brewing up something special in the back room...",
    "🔮 consulting the house oracle... gif incoming...",
    "🎪 the gif hamster is running on its wheel, one moment...",
    "🌀 channeling the creative energy of the house...",
    "🍳 cooking up a hot gif, don't touch the stove...",
    "🧶 knitting you a gif with love and care...",
    "🪩 the disco ball is spinning... gif loading...",
]

TIMEOUT_MESSAGES = [
    "⏱️ the gif server fell asleep on the couch again. poke it and try in a min?",
    "⏱️ timed out... the server is taking a nap like someone after house dinner",
    "⏱️ gif machine is buffering harder than the house wifi. try again shortly!",
    "⏱️ the gif gnomes are on break. they'll be back in a minute, promise",
    "⏱️ this is taking longer than deciding whose turn it is to do dishes. try again!",
]

CONNECTION_ERROR_MESSAGES = [
    "🔌 can't reach the gif server... did someone unplug it to charge their phone?",
    "🔌 gif server is MIA, like that one housemate who's 'definitely coming to the meeting'",
    "🔌 lost connection to the gif machine. it's probably restarting, give it a sec",
    "🔌 the gif server ghosted us. classic. try again in a minute!",
    "🔌 server's down... probably tripped the breaker again. brb",
]

GENERATION_FAILED_MESSAGES = [
    "❌ gif machine said no 😤 try a different emoji maybe?",
    "❌ that didn't work lol. the gif gods are displeased. try another template!",
    "❌ gif factory had a malfunction. it's not you, it's the server",
    "❌ nope. the gif gremlins ate this one. try again?",
    "❌ the vibes were off and the gif couldn't manifest. try a different one!",
]

GENERIC_ERROR_MESSAGES = [
    "😵 something broke and honestly idk what happened. try again?",
    "😵 the gif machine had a moment. we've all been there. try again!",
    "😵 oops. that wasn't supposed to happen. let's pretend it didn't and try again",
    "😵 well THAT was unexpected. like finding someone else's leftovers gone. try again?",
    "😵 a mystery error appeared! much like the mystery stain on the couch. try again!",
]

DOWNLOAD_ERROR_MESSAGES = [
    "❌ can't grab the image... am i invited to this channel? 👉👈",
    "❌ couldn't download that pic. make sure i'm in the channel! /invite @MakeSweet",
    "❌ i can see there's an image but i can't touch it. i need to be invited to the channel first!",
]

SUCCESS_MESSAGES = {
    "heart-locket": [
        "💖 love is in the air at the co-op",
        "💖 the locket has spoken. this is canon now",
        "💖 putting this on the house fridge",
        "💖 heart-locket-ified with care",
        "💖 this belongs in the house museum",
    ],
    "billboard": [
        "🏙️ your face, 40 feet tall. you're welcome",
        "🏙️ now THAT'S a billboard worth looking at",
        "🏙️ famous in the city. house legend status",
        "🏙️ this is going up on the house billboard",
        "🏙️ big picture energy",
    ],
    "flag": [
        "🏳️ flying this flag at the next house meeting",
        "🏳️ i pledge allegiance to this gif",
        "🏳️ the official flag of the co-op, as voted by me",
        "🏳️ let it wave, baby",
        "🏳️ this flag goes hard",
    ],
    "flying-bear": [
        "🐻 the bear has your image and it's not giving it back",
        "🐻 fly, bear, fly! take this masterpiece to the skies",
        "🐻 special delivery from the co-op bear",
        "🐻 a bear. flying. with your pic. you're welcome",
        "🐻 certified bear-approved content",
    ],
    "nesting-doll": [
        "🪆 it's dolls all the way down",
        "🪆 the nesting doll council has accepted your offering",
        "🪆 matryo-SHKA that's cool",
        "🪆 layers, like an onion. or a co-op house meeting agenda",
        "🪆 you've been doll-ified. no take-backs",
    ],
}

HOW_RESPONSES = [
    "react to any image with one of these bad boys:\n💖 heart locket · 🏙️ billboard · 🏳️ flag · 🐻 flying bear · 🪆 nesting doll",
    "just slap one of these emojis on a pic:\n💖 🏙️ 🏳️ 🐻 🪆\nand watch the magic happen ✨",
    "the sacred emojis:\n💖 = heart locket\n🏙️ = billboard\n🏳️ = flag\n🐻 = flying bear\n🪆 = nesting doll\nreact to an image and i do the rest 🫡",
]

# Track processed reactions to avoid duplicates
processed_reactions = set()
MAX_PROCESSED_SIZE = 10000


def download_image(url, headers=None):
    """Download an image and return the bytes, or None on failure."""
    try:
        resp = requests.get(url, headers=headers or {}, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 0:
            return resp.content
    except Exception as e:
        logger.warning(f"Failed to download image from {url}: {e}")
    return None


def get_user_avatar(client, user_id):
    """Fetch a user's Slack profile picture."""
    try:
        user_info = client.users_info(user=user_id)
        profile = user_info["user"]["profile"]
        # Try to get the largest available avatar
        avatar_url = (
            profile.get("image_512")
            or profile.get("image_192")
            or profile.get("image_72")
            or profile.get("image_48")
        )
        if avatar_url:
            return download_image(avatar_url)
    except Exception as e:
        logger.warning(f"Failed to get avatar for user {user_id}: {e}")
    return None


def get_message_poster_avatar(client, message):
    """Get the avatar of the person who posted the message."""
    user_id = message.get("user")
    if user_id:
        return get_user_avatar(client, user_id)
    return None


def fetch_message(client, channel, message_ts):
    """
    Fetch a message by timestamp. Tries conversations_history first (top-level),
    then falls back to conversations_replies (thread replies).
    """
    # Try top-level message first
    try:
        result = client.conversations_history(
            channel=channel,
            latest=message_ts,
            inclusive=True,
            limit=1,
        )
        messages = result.get("messages", [])
        if messages and messages[0].get("ts") == message_ts:
            return messages[0]
    except Exception as e:
        logger.warning(f"conversations_history failed: {e}")

    # Fall back to thread replies — the reacted message might be inside a thread
    try:
        result = client.conversations_replies(
            channel=channel,
            ts=message_ts,
            inclusive=True,
            limit=1,
        )
        messages = result.get("messages", [])
        for msg in messages:
            if msg.get("ts") == message_ts:
                return msg
    except Exception as e:
        logger.warning(f"conversations_replies failed: {e}")

    return None


def collect_images(client, message, reactor_user_id):
    """
    Collect images from a message, plus the reactor's and poster's avatars.
    Returns a dict with keys:
      - "message_images": list of image bytes from the message
      - "reactor_avatar": bytes or None
      - "poster_avatar": bytes or None
    """
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    auth_headers = {"Authorization": f"Bearer {bot_token}"}

    # Get all images from the message
    files = message.get("files", [])
    image_files = [f for f in files if f.get("mimetype", "").startswith("image/")]

    message_images = []
    for img_file in image_files:
        url = img_file.get("url_private_download") or img_file.get("url_private")
        if url:
            data = download_image(url, headers=auth_headers)
            if data:
                message_images.append(data)

    # Get avatars
    reactor_avatar = get_user_avatar(client, reactor_user_id)
    poster_avatar = get_message_poster_avatar(client, message)

    return {
        "message_images": message_images,
        "reactor_avatar": reactor_avatar,
        "poster_avatar": poster_avatar,
    }


def build_form_files(template, images_info):
    """
    Smartly assign images to form fields based on what's available.

    Strategy for multi-image templates:
    - heart-locket (2 slots): message image + reactor's avatar
    - nesting-doll (3 slots): message image + reactor avatar + poster avatar

    Falls back gracefully:
    - Multiple message images? Use those first.
    - Only one image? Mix in avatars.
    - Still not enough? Duplicate what we have.
    """
    fields = TEMPLATE_FIELDS.get(template, ["image"])
    num_needed = len(fields)

    msg_images = images_info["message_images"]
    reactor_avatar = images_info["reactor_avatar"]
    poster_avatar = images_info["poster_avatar"]

    if num_needed == 1:
        # Simple: just use the first message image
        img = msg_images[0] if msg_images else None
        if not img:
            return None
        return {fields[0]: ("image.png", img, "image/png")}

    # Build a pool of available images in priority order
    pool = []

    if num_needed == 2:
        # heart-locket: message image on left, reactor avatar on right
        if msg_images:
            pool.append(msg_images[0])
        if reactor_avatar:
            pool.append(reactor_avatar)
        # If we have 2+ message images, prefer those
        if len(msg_images) >= 2:
            pool = msg_images[:2]
        # Still need more? Add poster avatar or duplicate
        if len(pool) < 2 and poster_avatar and poster_avatar not in pool:
            pool.append(poster_avatar)

    elif num_needed == 3:
        # nesting-doll: message images first, then avatars
        if len(msg_images) >= 3:
            pool = msg_images[:3]
        elif len(msg_images) >= 2:
            pool = msg_images[:2]
            if reactor_avatar:
                pool.append(reactor_avatar)
            elif poster_avatar:
                pool.append(poster_avatar)
        elif len(msg_images) == 1:
            pool.append(msg_images[0])
            if reactor_avatar:
                pool.append(reactor_avatar)
            if poster_avatar and poster_avatar != reactor_avatar:
                pool.append(poster_avatar)
        else:
            # No message images at all
            return None

    # Pad pool by duplicating if we still don't have enough
    while len(pool) < num_needed:
        pool.append(pool[0] if pool else None)

    if not pool or pool[0] is None:
        return None

    # Map images to form fields
    form_files = {}
    for i, field_name in enumerate(fields):
        form_files[field_name] = ("image.png", pool[i], "image/png")

    return form_files


@app.event("message")
def handle_message(event, client):
    """If someone replies 'how' to a message with images, reply with the supported emojis."""
    try:
        text = (event.get("text") or "").strip().lower()
        if text != "how":
            return

        # Only respond in threads (replies to a message)
        thread_ts = event.get("thread_ts")
        if not thread_ts:
            return

        channel = event["channel"]

        # Check if the parent message has images
        parent = fetch_message(client, channel, thread_ts)
        if not parent:
            return

        files = parent.get("files", [])
        has_images = any(f.get("mimetype", "").startswith("image/") for f in files)

        if not has_images:
            return

        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=random.choice(HOW_RESPONSES),
        )

    except Exception as e:
        logger.error(f"Error handling 'how' message: {e}", exc_info=True)


@app.event("reaction_added")
def handle_reaction_added(event, client):
    try:
        reaction = event["reaction"]
        template = EMOJI_TEMPLATE_MAP.get(reaction)

        if not template:
            return

        item = event["item"]
        if item["type"] != "message":
            return

        channel = item["channel"]
        message_ts = item["ts"]
        reactor_user = event["user"]

        # Deduplicate
        reaction_key = f"{channel}:{message_ts}:{template}"
        if reaction_key in processed_reactions:
            logger.info(f"Already processed {reaction_key}, skipping")
            return
        processed_reactions.add(reaction_key)

        if len(processed_reactions) > MAX_PROCESSED_SIZE:
            processed_reactions.clear()

        logger.info(f"Processing reaction '{reaction}' -> template '{template}' in {channel}")

        # Fetch the message (works for both top-level and thread replies)
        message = fetch_message(client, channel, message_ts)

        if not message:
            logger.warning("Could not find the reacted message")
            return

        # Check for images
        files = message.get("files", [])
        has_images = any(f.get("mimetype", "").startswith("image/") for f in files)

        if not has_images:
            logger.info("No image files in message, skipping")
            return

        # Post a "working on it" indicator
        try:
            thinking_msg = client.chat_postMessage(
                channel=channel,
                thread_ts=message_ts,
                text=random.choice(THINKING_MESSAGES),
            )
        except Exception:
            thinking_msg = None

        # Collect all available images (message images + avatars)
        logger.info("Collecting images (message files + user avatars)...")
        images_info = collect_images(client, message, reactor_user)

        if not images_info["message_images"]:
            logger.warning("Failed to download any message images")
            _update_or_post(client, channel, message_ts, thinking_msg,
                           random.choice(DOWNLOAD_ERROR_MESSAGES))
            return

        # Build the smart form data
        form_files = build_form_files(template, images_info)
        if not form_files:
            logger.error("Failed to build form files")
            _update_or_post(client, channel, message_ts, thinking_msg,
                           random.choice(GENERATION_FAILED_MESSAGES))
            return

        fields = TEMPLATE_FIELDS.get(template, ["image"])
        source_info = []
        if len(fields) > 1:
            source_info.append(f"{len(images_info['message_images'])} message image(s)")
            if images_info["reactor_avatar"]:
                source_info.append("reactor's avatar")
            if images_info["poster_avatar"]:
                source_info.append("poster's avatar")
            logger.info(f"Using: {', '.join(source_info)}")

        # Generate the GIF
        logger.info(f"Generating {template} GIF via MakeSweet...")
        try:
            gif_response = requests.post(
                f"{MAKESWEET_URL}/api/gif/{template}",
                files=form_files,
                timeout=120,
            )
        except requests.Timeout:
            logger.error("MakeSweet request timed out")
            _update_or_post(client, channel, message_ts, thinking_msg,
                           random.choice(TIMEOUT_MESSAGES))
            return
        except requests.ConnectionError:
            logger.error("Could not connect to MakeSweet server")
            _update_or_post(client, channel, message_ts, thinking_msg,
                           random.choice(CONNECTION_ERROR_MESSAGES))
            return

        if gif_response.status_code != 200:
            logger.error(f"MakeSweet error: {gif_response.status_code} - {gif_response.text[:200]}")
            _update_or_post(client, channel, message_ts, thinking_msg,
                           random.choice(GENERATION_FAILED_MESSAGES))
            return

        # Pick a fun success message for this template
        success_msg = random.choice(SUCCESS_MESSAGES.get(template, ["✨ here u go"]))

        # Delete the "working on it" message
        if thinking_msg:
            try:
                client.chat_delete(
                    channel=channel,
                    ts=thinking_msg["ts"],
                )
            except Exception:
                pass  # Bot might not have permission to delete

        # Upload GIF to Slack as a threaded reply
        logger.info("Uploading GIF to Slack...")
        client.files_upload_v2(
            channel=channel,
            thread_ts=message_ts,
            file_uploads=[
                {
                    "content": gif_response.content,
                    "filename": f"{template}.gif",
                    "title": template,
                }
            ],
            initial_comment=success_msg,
        )

        logger.info("GIF posted successfully!")

    except Exception as e:
        logger.error(f"Error processing reaction: {e}", exc_info=True)
        # Try to notify the user something went wrong
        try:
            client.chat_postMessage(
                channel=channel,
                thread_ts=message_ts,
                text=random.choice(GENERIC_ERROR_MESSAGES),
            )
        except Exception:
            pass


def _update_or_post(client, channel, thread_ts, thinking_msg, text):
    """Update the thinking message with an error, or post a new one."""
    if thinking_msg:
        try:
            client.chat_update(
                channel=channel,
                ts=thinking_msg["ts"],
                text=text,
            )
            return
        except Exception:
            pass
    try:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=text,
        )
    except Exception:
        pass


# Health check endpoint for Render
flask_app = Flask(__name__)


@flask_app.route("/")
@flask_app.route("/health")
def health():
    return "MakeSweet Slack Bot is running! 🎬"


def start_flask():
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Health check server started")

    logger.info("Starting MakeSweet Slack Bot in Socket Mode...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
