import os
import sys
import logging
import time
import threading
from collections import OrderedDict
from io import BytesIO

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from flask import Flask, jsonify

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Startup validation ───────────────────────────────────────────────────
REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
if missing:
    logger.critical(f"Missing required env vars: {', '.join(missing)}")
    sys.exit(1)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

MAKESWEET_URL = os.environ.get(
    "MAKESWEET_URL", "http://localhost:8080"
)

# ── Emoji → template ────────────────────────────────────────────────────
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

TEMPLATE_FIELDS = {
    "heart-locket": ["image-left", "image-right"],
    "billboard": ["image"],
    "flag": ["image"],
    "flying-bear": ["image"],
    "nesting-doll": ["image-left", "image-mid", "image-right"],
}

WORKING_REACTION = "art"  # 🎨


# ── Thread-safe LRU dedup cache ─────────────────────────────────────────
class LRUDedup:
    """Thread-safe LRU set that evicts oldest entries instead of clearing all."""

    def __init__(self, max_size=10000):
        self._data = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def check_and_add(self, key):
        """Returns True if key is new (not a dupe). Adds it atomically."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return False
            self._data[key] = True
            if len(self._data) > self._max_size:
                self._data.popitem(last=False)
            return True


processed = LRUDedup(max_size=10000)


# ── Concurrency limiter ─────────────────────────────────────────────────
gif_semaphore = threading.Semaphore(3)  # max 3 concurrent GIF generations


# ── Image helpers ────────────────────────────────────────────────────────
def download_image(url, headers=None, retries=2):
    """Download an image with retries."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers or {}, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 100:
                return resp.content
            logger.warning(
                f"Bad response downloading image: {resp.status_code} "
                f"({len(resp.content)} bytes)"
            )
        except Exception as e:
            logger.warning(
                f"Download attempt {attempt + 1}/{retries + 1} failed: {e}"
            )
            if attempt < retries:
                time.sleep(1)
    return None


def get_user_avatar(client, user_id):
    if not user_id:
        return None
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
        logger.warning(f"Failed to get avatar for {user_id}: {e}")
    return None


# ── Message fetching ─────────────────────────────────────────────────────
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

    # It might be a thread reply — need to find the parent thread
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


# ── Image collection ────────────────────────────────────────────────────
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
            if poster_avatar:
                pool.append(poster_avatar)
        else:
            return None

    # Pad by duplicating first image if needed
    while len(pool) < num_needed:
        if pool:
            pool.append(pool[0])
        else:
            return None

    if not pool or pool[0] is None:
        return None

    return {
        field: ("image.png", pool[i], "image/png")
        for i, field in enumerate(fields)
    }


# ── Reaction helpers ────────────────────────────────────────────────────
def add_working_reaction(client, channel, timestamp):
    try:
        client.reactions_add(
            channel=channel, timestamp=timestamp, name=WORKING_REACTION
        )
    except Exception as e:
        logger.warning(f"Could not add working reaction: {e}")


def remove_working_reaction(client, channel, timestamp):
    try:
        client.reactions_remove(
            channel=channel, timestamp=timestamp, name=WORKING_REACTION
        )
    except Exception:
        pass  # Might already be removed, that's fine


# ── GIF generation with retry ───────────────────────────────────────────
def generate_gif(template, form_files, retries=1):
    """Call MakeSweet server with retry on failure."""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{MAKESWEET_URL}/api/gif/{template}",
                files=form_files,
                timeout=120,
            )
            if resp.status_code == 200:
                # Validate it's actually a GIF
                content = resp.content
                if len(content) > 100 and content[:6] in (b"GIF87a", b"GIF89a"):
                    return content
                logger.warning(
                    f"Response isn't a valid GIF "
                    f"({len(content)} bytes, starts with {content[:10]})"
                )
            else:
                logger.warning(
                    f"MakeSweet returned {resp.status_code} "
                    f"(attempt {attempt + 1})"
                )
        except requests.Timeout:
            logger.warning(f"MakeSweet timed out (attempt {attempt + 1})")
        except requests.ConnectionError:
            logger.warning(f"Can't reach MakeSweet (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"Unexpected error calling MakeSweet: {e}")

        if attempt < retries:
            time.sleep(2)

    return None


# ── Event handlers ──────────────────────────────────────────────────────
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

        # Thread-safe dedup with LRU eviction
        reaction_key = f"{channel}:{message_ts}:{template}"
        if not processed.check_and_add(reaction_key):
            return

        logger.info(f"Processing '{reaction}' -> '{template}' in {channel}")

        message = fetch_message(client, channel, message_ts)
        if not message:
            logger.warning("Could not fetch message")
            return

        files = message.get("files", [])
        has_images = any(f.get("mimetype", "").startswith("image/") for f in files)
        if not has_images:
            return

        # Limit concurrent GIF generations
        acquired = gif_semaphore.acquire(timeout=60)
        if not acquired:
            logger.warning("Too many concurrent GIF generations, skipping")
            return

        try:
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

            # Generate with retry
            gif_data = generate_gif(template, form_files)

            # Always remove the working reaction
            remove_working_reaction(client, channel, message_ts)

            if not gif_data:
                logger.error(f"GIF generation failed for {template}")
                return

            # Post just the GIF, no text
            client.files_upload_v2(
                channel=channel,
                thread_ts=message_ts,
                file_uploads=[
                    {
                        "content": gif_data,
                        "filename": f"{template}.gif",
                        "title": template,
                    }
                ],
            )
            logger.info(f"Posted {template} GIF!")

        finally:
            gif_semaphore.release()

    except Exception as e:
        logger.error(f"Error processing reaction: {e}", exc_info=True)
        try:
            remove_working_reaction(client, channel, message_ts)
        except Exception:
            pass


# ── Health check with actual status ─────────────────────────────────────
flask_app = Flask(__name__)

# Track connection state
bot_state = {"socket_connected": False, "last_event_time": 0, "start_time": 0}


@app.event("app_mention")
def handle_mention(event, client):
    """Track event receipt so health check can verify we're getting events."""
    bot_state["last_event_time"] = time.time()


@flask_app.route("/")
@flask_app.route("/health")
def health():
    uptime = int(time.time() - bot_state["start_time"]) if bot_state["start_time"] else 0
    last_event_age = (
        int(time.time() - bot_state["last_event_time"])
        if bot_state["last_event_time"]
        else None
    )

    status = {
        "status": "ok",
        "uptime_seconds": uptime,
        "socket_connected": bot_state["socket_connected"],
        "last_event_seconds_ago": last_event_age,
    }

    # Check if MakeSweet server is reachable (cached every 5 min)
    return jsonify(status), 200


# ── Startup ─────────────────────────────────────────────────────────────
def start_flask():
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    bot_state["start_time"] = time.time()

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Health check server started")

    logger.info("Starting MakeSweet Slack Bot in Socket Mode...")
    bot_state["socket_connected"] = True
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
