import os
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
# Some templates need multiple image fields
TEMPLATE_FIELDS = {
    "heart-locket": ["image-left", "image-right"],
    "billboard": ["image"],
    "flag": ["image"],
    "flying-bear": ["image"],
    "nesting-doll": ["image-left", "image-mid", "image-right"],
}

# Track processed reactions to avoid duplicates
processed_reactions = set()
MAX_PROCESSED_SIZE = 10000


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
        user = event["user"]

        # Deduplicate
        reaction_key = f"{channel}:{message_ts}:{template}"
        if reaction_key in processed_reactions:
            logger.info(f"Already processed {reaction_key}, skipping")
            return
        processed_reactions.add(reaction_key)

        # Prevent unbounded memory growth
        if len(processed_reactions) > MAX_PROCESSED_SIZE:
            processed_reactions.clear()

        logger.info(f"Processing reaction '{reaction}' -> template '{template}' in {channel}")

        # Fetch the message to find images
        result = client.conversations_history(
            channel=channel,
            latest=message_ts,
            inclusive=True,
            limit=1,
        )

        if not result.get("messages"):
            logger.warning("No messages found")
            return

        message = result["messages"][0]

        # Find image files
        files = message.get("files", [])
        image_files = [
            f
            for f in files
            if f.get("mimetype", "").startswith("image/")
        ]

        if not image_files:
            logger.info("No image files in message, skipping")
            return

        image_file = image_files[0]

        # Download the image from Slack
        image_url = image_file.get("url_private_download") or image_file.get("url_private")
        if not image_url:
            logger.warning("No download URL for image")
            return

        logger.info("Downloading image from Slack...")
        image_response = requests.get(
            image_url,
            headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
            timeout=30,
        )

        if image_response.status_code != 200:
            logger.error(f"Failed to download image: {image_response.status_code}")
            return

        # Build the form fields based on the template
        fields = TEMPLATE_FIELDS.get(template, ["image"])
        form_files = {}
        for field_name in fields:
            form_files[field_name] = ("image.png", image_response.content, "image/png")

        # Send to MakeSweet server
        logger.info(f"Generating {template} GIF via MakeSweet ({len(fields)} image field(s))...")
        gif_response = requests.post(
            f"{MAKESWEET_URL}/api/gif/{template}",
            files=form_files,
            timeout=120,
        )

        if gif_response.status_code != 200:
            logger.error(f"MakeSweet error: {gif_response.status_code} - {gif_response.text[:200]}")
            return

        # Upload GIF to Slack as a reply
        logger.info("Uploading GIF to Slack...")
        client.files_upload_v2(
            channel=channel,
            thread_ts=message_ts,
            file_uploads=[
                {
                    "content": gif_response.content,
                    "filename": f"{template}.gif",
                    "title": f"{template}",
                }
            ],
            initial_comment=f"✨ Here's your *{template}* GIF!",
        )

        logger.info("GIF posted successfully!")

    except Exception as e:
        logger.error(f"Error processing reaction: {e}", exc_info=True)


# Health check endpoint so Render keeps the service alive
flask_app = Flask(__name__)


@flask_app.route("/")
@flask_app.route("/health")
def health():
    return "MakeSweet Slack Bot is running! 🎬"


def start_flask():
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    # Start Flask health check in background thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Health check server started")

    # Start Socket Mode handler (blocks main thread)
    logger.info("Starting MakeSweet Slack Bot in Socket Mode...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
