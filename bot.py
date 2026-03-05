import os
import logging
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from flask import Flask
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

MAKESWEET_URL = os.environ.get("MAKESWEET_URL", "https://makesweet-server.onrender.com")

# Emoji -> template mapping
EMOJI_TEMPLATE_MAP = {
    "sparkling_heart": "heart-locket",
    "heart": "heart-locket",
    "hearts": "heart-locket",
    "heartpulse": "heart-locket",
    "revolving_hearts": "heart-locket",
    "two_hearts": "heart-locket",
    "heart_decoration": "heart-locket",
    "cityscape": "billboard",
    "city_sunrise": "billboard",
    "city_sunset": "billboard",
    "checkered_flag": "flag",
    "waving_white_flag": "flag",
    "triangular_flag_on_post": "flag",
    "flag-white": "flag",
    "bear": "flying-bear",
    "teddy_bear": "flying-bear",
    "nesting_dolls": "nesting-doll",
}

# Template -> form fields
TEMPLATE_FIELDS = {
    "heart-locket": ["image-left", "image-right"],
    "billboard": ["image"],
    "flag": ["image"],
    "flying-bear": ["image"],
    "nesting-doll": ["image-left", "image-mid", "image-right"],
}

# Bot reacts with this while working, removes it when done
WORKING_REACTION = "art"  # 🎨

processed_reactions = set()
MAX_PROCESSED_SIZE = 10000


def download_image(url, headers=None):
    try:
        resp = requests.get(url, headers=headers or {}, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 0:
            return resp.content
    except Exception as e:
        logger.warning(f"Failed to download image from {url}: {e}")
    return None


def get_user_avatar(client, user_id):
    try:
        user_info = client.users_info(user=user_id)
        profile = user_info["user"]["profile"]
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


def fetch_message(client, channel, message_ts):
    """Fetch a message — tries top-level first, then thread replies."""
    try:
        result = client.conversations_history(
            channel=channel, latest=message_ts, inclusive=True, limit=1
        )
        messages = result.get("messages", [])
        if messages and messages[0].get("ts") == message_ts:
            return messages[0]
    except Exception as e:
        logger.warning(f"conversations_history failed: {e}")

    try:
        result = client.conversations_replies(
            channel=channel, ts=message_ts, inclusive=True, limit=1
        )
        messages = result.get("messages", [])
        for msg in messages:
            if msg.get("ts") == message_ts:
                return msg
    except Exception as e:
        logger.warning(f"conversations_replies failed: {e}")

    return None


def collect_images(client, message, reactor_user_id):
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    auth_headers = {"Authorization": f"Bearer {bot_token}"}

    files = message.get("files", [])
    image_files = [f for f in files if f.get("mimetype", "").startswith("image/")]

    message_images = []
    for img_file in image_files:
        url = img_file.get("url_private_download") or img_file.get("url_private")
        if url:
            data = download_image(url, headers=auth_headers)
            if data:
                message_images.append(data)

    reactor_avatar = get_user_avatar(client, reactor_user_id)
    poster_id = message.get("user")
    poster_avatar = get_user_avatar(client, poster_id) if poster_id else None

    return {
        "message_images": message_images,
        "reactor_avatar": reactor_avatar,
        "poster_avatar": poster_avatar,
    }


def build_form_files(template, images_info):
    fields = TEMPLATE_FIELDS.get(template, ["image"])
    num_needed = len(fields)

    msg_images = images_info["message_images"]
    reactor_avatar = images_info["reactor_avatar"]
    poster_avatar = images_info["poster_avatar"]

    if num_needed == 1:
        img = msg_images[0] if msg_images else None
        if not img:
            return None
        return {fields[0]: ("image.png", img, "image/png")}

    pool = []

    if num_needed == 2:
        if len(msg_images) >= 2:
            pool = msg_images[:2]
        else:
            if msg_images:
                pool.append(msg_images[0])
            if reactor_avatar:
                pool.append(reactor_avatar)
            if len(pool) < 2 and poster_avatar:
                pool.append(poster_avatar)

    elif num_needed == 3:
        if len(msg_images) >= 3:
            pool = msg_images[:3]
        elif len(msg_images) >= 2:
            pool = msg_images[:2]
            pool.append(reactor_avatar or poster_avatar)
        elif len(msg_images) == 1:
            pool.append(msg_images[0])
            if reactor_avatar:
                pool.append(reactor_avatar)
            if poster_avatar and poster_avatar != reactor_avatar:
                pool.append(poster_avatar)
        else:
            return None

    # Pad by duplicating if needed
    while len(pool) < num_needed:
        pool.append(pool[0] if pool else None)

    if not pool or pool[0] is None:
        return None

    return {field: ("image.png", pool[i], "image/png") for i, field in enumerate(fields)}


def add_working_reaction(client, channel, timestamp):
    """Add 🎨 reaction to show we're working."""
    try:
        client.reactions_add(channel=channel, timestamp=timestamp, name=WORKING_REACTION)
    except Exception as e:
        logger.warning(f"Could not add working reaction: {e}")


def remove_working_reaction(client, channel, timestamp):
    """Remove 🎨 reaction when done."""
    try:
        client.reactions_remove(channel=channel, timestamp=timestamp, name=WORKING_REACTION)
    except Exception as e:
        logger.warning(f"Could not remove working reaction: {e}")


@app.event("message")
def handle_message(event, client):
    """Reply 'how' in a thread with an image -> show supported emojis."""
    try:
        text = (event.get("text") or "").strip().lower()
        if text != "how":
            return

        thread_ts = event.get("thread_ts")
        if not thread_ts:
            return

        channel = event["channel"]
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
            text="💖 🏙️ 🏳️ 🐻 🪆",
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
            return
        processed_reactions.add(reaction_key)
        if len(processed_reactions) > MAX_PROCESSED_SIZE:
            processed_reactions.clear()

        logger.info(f"Processing '{reaction}' -> '{template}' in {channel}")

        message = fetch_message(client, channel, message_ts)
        if not message:
            return

        files = message.get("files", [])
        has_images = any(f.get("mimetype", "").startswith("image/") for f in files)
        if not has_images:
            return

        # React with 🎨 to show we're working
        add_working_reaction(client, channel, message_ts)

        images_info = collect_images(client, message, reactor_user)

        if not images_info["message_images"]:
            logger.warning("Failed to download message images")
            remove_working_reaction(client, channel, message_ts)
            return

        form_files = build_form_files(template, images_info)
        if not form_files:
            remove_working_reaction(client, channel, message_ts)
            return

        # Generate the GIF
        logger.info(f"Generating {template} GIF...")
        try:
            gif_response = requests.post(
                f"{MAKESWEET_URL}/api/gif/{template}",
                files=form_files,
                timeout=120,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            logger.error(f"MakeSweet request failed: {e}")
            remove_working_reaction(client, channel, message_ts)
            return

        if gif_response.status_code != 200:
            logger.error(f"MakeSweet error: {gif_response.status_code}")
            remove_working_reaction(client, channel, message_ts)
            return

        # Remove 🎨 reaction
        remove_working_reaction(client, channel, message_ts)

        # Post just the GIF, no text
        logger.info("Uploading GIF...")
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
        )

        logger.info("GIF posted!")

    except Exception as e:
        logger.error(f"Error processing reaction: {e}", exc_info=True)
        try:
            remove_working_reaction(client, channel, message_ts)
        except Exception:
            pass


# Health check
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
