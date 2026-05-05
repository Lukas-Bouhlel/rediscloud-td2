import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

import redis
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit
from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("td-cloud")

app = Flask(__name__, static_folder="static", static_url_path="")
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_timeout=120,
    ping_interval=25,
)

# Configuration Redis
r = redis.Redis(
    host=os.environ.get("REDIS_HOST", "127.0.0.1"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    username=os.environ.get("REDIS_USERNAME"),
    password=os.environ.get("REDIS_PASSWORD"),
    decode_responses=True,
)

# Configuration Pub/Sub (supporte plusieurs noms d'env)
PROJECT_ID = (
    os.environ.get("GCP_PROJECT_ID")
    or os.environ.get("PROJECT_ID")
    or "test-project"
)
TOPIC_ID = os.environ.get("TOPIC_NAME") or os.environ.get("PUBSUB_TOPIC") or "redis-updates"
SERVER_ID = (
    os.environ.get("SERVER_ID")
    or os.environ.get("K_SERVICE")
    or os.environ.get("HOSTNAME")
    or "local"
)

_pubsub_enabled = os.environ.get("PUBSUB_ENABLED", "1").lower() not in {"0", "false", "no"}
if os.environ.get("DISABLE_PUBSUB", "").lower() in {"1", "true", "yes"}:
    _pubsub_enabled = False

_pubsub_auto_create = os.environ.get("PUBSUB_AUTO_CREATE", "0").lower() in {
    "1",
    "true",
    "yes",
}

publisher = pubsub_v1.PublisherClient() if _pubsub_enabled else None
subscriber = pubsub_v1.SubscriberClient() if _pubsub_enabled else None


def _sanitize_subscription_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9\-_.]", "-", value)
    return safe[:255]


SUBSCRIPTION_ID = (
    os.environ.get("SUBSCRIPTION_NAME")
    or os.environ.get("PUBSUB_SUBSCRIPTION")
    or _sanitize_subscription_id(f"{TOPIC_ID}-{SERVER_ID}")
)

TOPIC_PATH = publisher.topic_path(PROJECT_ID, TOPIC_ID) if publisher else None
SUBSCRIPTION_PATH = (
    subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID) if subscriber else None
)


def ensure_topic_and_subscription() -> None:
    if not _pubsub_enabled or not publisher or not subscriber:
        return

    try:
        publisher.create_topic(request={"name": TOPIC_PATH})
    except AlreadyExists:
        pass

    try:
        subscriber.create_subscription(
            request={"name": SUBSCRIPTION_PATH, "topic": TOPIC_PATH}
        )
    except AlreadyExists:
        pass


def load_initial_state() -> dict:
    result = {}
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match="event:*", count=100)
        for key in keys:
            value = r.get(key)
            if value:
                result[key] = {
                    "data": json.loads(value),
                    "ttl_remaining_seconds": r.ttl(key),
                }
        if cursor == 0:
            break
    return result


@socketio.on("connect")
def on_connect():
    state = load_initial_state()
    emit(
        "initial_state",
        {"server_id": SERVER_ID, "count": len(state), "entries": state},
    )


def handle_pubsub_message(message: pubsub_v1.subscriber.message.Message) -> None:
    try:
        redis_key = message.data.decode("utf-8")
        logger.info("Pub/Sub message received: %s", redis_key)
        value = r.get(redis_key)
        payload = {
            "server_id": SERVER_ID,
            "redis_key": redis_key,
            "data": json.loads(value) if value else None,
            "ttl_remaining_seconds": r.ttl(redis_key),
        }
        emit_update(payload)
        message.ack()
        logger.info("Pub/Sub message acked: %s", redis_key)
    except Exception as exc:
        logger.exception("Pub/Sub handler error: %s", exc)
        message.nack()


def emit_update(payload: dict) -> None:
    # Pub/Sub callback runs in a native thread; schedule emit in Socket.IO context.
    socketio.start_background_task(_emit_update_task, payload)


def _emit_update_task(payload: dict) -> None:
    socketio.emit("update", payload)


def start_pubsub_listener() -> None:
    if not _pubsub_enabled or not publisher or not subscriber:
        logger.info("Pub/Sub disabled: listener not started.")
        return

    def _run() -> None:
        if _pubsub_auto_create:
            try:
                ensure_topic_and_subscription()
            except Exception as exc:
                # Continue even if creation fails (e.g. missing pubsub.admin);
                # subscriptions may already exist.
                logger.warning(
                    "Pub/Sub setup failed: %s. Continuing with existing resources.", exc
                )
        else:
            logger.info(
                "Pub/Sub auto-create disabled (PUBSUB_AUTO_CREATE=0): using existing topic/subscription."
            )

        logger.info("Pub/Sub listener subscribing to: %s", SUBSCRIPTION_PATH)
        future = subscriber.subscribe(SUBSCRIPTION_PATH, callback=handle_pubsub_message)
        try:
            future.result()
        except Exception as exc:
            logger.exception("Pub/Sub listener stopped: %s", exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


start_pubsub_listener()


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/publish", methods=["POST"])
def publish():
    try:
        data = request.get_json(silent=True)
        if data is None:
            raw = request.get_data(cache=False, as_text=True) or ""
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return jsonify({"error": "Champ 'message' requis"}), 400
        if "message" not in data:
            return jsonify({"error": "Champ 'message' requis"}), 400

        entry = {
            "message": data["message"],
            "server_id": SERVER_ID,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Stockage dans Redis (source de verite)
        key = f"event:{SERVER_ID}:{entry['published_at']}"
        r.setex(key, 3600, json.dumps(entry))

        # 2. Diffusion via Pub/Sub (alerte pour les autres instances)
        if _pubsub_enabled and publisher and TOPIC_PATH:
            future = publisher.publish(TOPIC_PATH, key.encode("utf-8"))
            message_id = future.result(timeout=15)
            logger.info("Pub/Sub publish success: key=%s message_id=%s", key, message_id)
        else:
            payload = {
                "server_id": SERVER_ID,
                "redis_key": key,
                "data": entry,
                "ttl_remaining_seconds": r.ttl(key),
            }
            emit_update(payload)

        return jsonify({"status": "published", "redis_key": key, "data": entry})
    except Exception as exc:
        logger.exception("Publish failed: %s", exc)
        return jsonify({"error": "Publish failed", "details": str(exc)}), 500


@app.route("/data")
def data():
    state = load_initial_state()
    return jsonify({"server_id": SERVER_ID, "count": len(state), "entries": state})


@app.route("/health")
def health():
    try:
        r.ping()
        return jsonify({"status": "healthy", "server_id": SERVER_ID, "redis": "connected"})
    except Exception as exc:
        return jsonify({"status": "unhealthy", "error": str(exc)}), 503


if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
        use_reloader=False,
    )
