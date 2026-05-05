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
from google.cloud import firestore
from google.cloud import pubsub_v1
from google.cloud import storage as gcs
from google.cloud import tasks_v2

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

PROJECT_ID = (
    os.environ.get("GCP_PROJECT_ID")
    or os.environ.get("PROJECT_ID")
    or "test-project"
)
REGION = os.environ.get("REGION", "europe-west1")
TOPIC_ID = os.environ.get("TOPIC_NAME") or os.environ.get("PUBSUB_TOPIC") or "game-events"
SERVER_ID = (
    os.environ.get("SERVER_ID")
    or os.environ.get("K_SERVICE")
    or os.environ.get("HOSTNAME")
    or "local"
)

TASK_QUEUE = os.environ.get("TASK_QUEUE", "game-events-queue")
PROCESSOR_URL = os.environ.get("PROCESSOR_URL", "").rstrip("/")
SNAPSHOT_BUCKET = os.environ.get("SNAPSHOT_BUCKET", "")
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "5"))
RATE_WINDOW_SECONDS = 60
ADMIN_KEY = os.environ.get("ADMIN_KEY", "changeme")

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
TOPIC_PATH = publisher.topic_path(PROJECT_ID, TOPIC_ID) if publisher else None


def _init_optional_client(factory, name: str):
    try:
        return factory()
    except Exception as exc:
        logger.warning("%s client disabled: %s", name, exc)
        return None


tasks_client = _init_optional_client(tasks_v2.CloudTasksClient, "Cloud Tasks")
storage_client = _init_optional_client(gcs.Client, "Cloud Storage")
firestore_client = _init_optional_client(firestore.Client, "Firestore")

PROTECTED_ROUTES = {"/publish"}


def _sanitize_subscription_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9\-_.]", "-", value)
    return safe[:255]


SUBSCRIPTION_ID = (
    os.environ.get("SUBSCRIPTION_NAME")
    or os.environ.get("PUBSUB_SUBSCRIPTION")
    or _sanitize_subscription_id(f"td-redis-sub-{SERVER_ID}")
)
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


def _create_snapshot_task(redis_key: str) -> None:
    if not tasks_client:
        return

    if not PROJECT_ID or not TASK_QUEUE or not PROCESSOR_URL:
        logger.info(
            "Cloud Tasks skipped (missing config): project=%s queue=%s processor_url=%s",
            bool(PROJECT_ID),
            bool(TASK_QUEUE),
            bool(PROCESSOR_URL),
        )
        return

    queue_path = tasks_client.queue_path(PROJECT_ID, REGION, TASK_QUEUE)
    payload = json.dumps({"redis_key": redis_key}).encode("utf-8")

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{PROCESSOR_URL}/process",
            "headers": {"Content-Type": "application/json"},
            "body": payload,
        }
    }

    tasks_client.create_task(request={"parent": queue_path, "task": task})


@firestore.transactional
def _rate_limit_transaction(transaction, doc_ref, now: datetime) -> bool:
    snapshot = doc_ref.get(transaction=transaction)
    data = snapshot.to_dict() if snapshot.exists else {}

    window_start = data.get("window_start")
    count = int(data.get("count", 0))

    if not isinstance(window_start, datetime):
        window_start = now
        count = 0

    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)

    if (now - window_start).total_seconds() >= RATE_WINDOW_SECONDS:
        window_start = now
        count = 0

    if count >= RATE_LIMIT_PER_MIN:
        return False

    transaction.set(
        doc_ref,
        {
            "count": count + 1,
            "window_start": window_start,
            "last_request": now,
        },
        merge=True,
    )
    return True


def _check_rate_limit(player_id: str) -> bool:
    if not firestore_client:
        return True

    doc_ref = firestore_client.collection("rate_limits").document(player_id)
    tx = firestore_client.transaction()
    now = datetime.now(timezone.utc)
    return _rate_limit_transaction(tx, doc_ref, now)


def _update_analytics_async(player_id: str) -> None:
    if not firestore_client:
        return

    def _write() -> None:
        try:
            doc_ref = firestore_client.collection("analytics").document(player_id)
            now = datetime.now(timezone.utc)
            snapshot = doc_ref.get()

            payload = {
                "total_requests": firestore.Increment(1),
                "total_events": firestore.Increment(1),
                "last_seen": now,
            }
            if not snapshot.exists:
                payload["first_seen"] = now

            doc_ref.set(payload, merge=True)
        except Exception as exc:
            logger.warning("Analytics write failed: %s", exc)

    threading.Thread(target=_write, daemon=True).start()


@app.before_request
def rate_limit_middleware():
    if request.path not in PROTECTED_ROUTES or request.method != "POST":
        return None

    player_id = request.headers.get("X-Player-ID", "anonymous")

    try:
        allowed = _check_rate_limit(player_id)
    except Exception as exc:
        # fail-open: ne pas bloquer le gameplay si Firestore est indisponible.
        logger.warning("Rate limit check failed, request allowed: %s", exc)
        return None

    if not allowed:
        return (
            jsonify(
                {
                    "error": "Rate limit exceeded",
                    "limit": RATE_LIMIT_PER_MIN,
                    "window": f"{RATE_WINDOW_SECONDS}s",
                    "player_id": player_id,
                }
            ),
            429,
        )

    return None


def _read_json_payload() -> dict:
    data = request.get_json(silent=True)
    if data is not None:
        return data

    raw = request.get_data(cache=False, as_text=True) or ""
    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


start_pubsub_listener()


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/publish", methods=["POST"])
def publish():
    try:
        data = _read_json_payload()
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

        # 3. Tache asynchrone pour snapshot (non bloquante)
        try:
            _create_snapshot_task(key)
        except Exception as exc:
            logger.warning("Cloud Task enqueue failed: %s", exc)

        player_id = request.headers.get("X-Player-ID", "anonymous")
        _update_analytics_async(player_id)

        return jsonify({"status": "published", "redis_key": key, "data": entry})
    except Exception as exc:
        logger.exception("Publish failed: %s", exc)
        return jsonify({"error": "Publish failed", "details": str(exc)}), 500


@app.route("/process", methods=["POST"])
def process():
    try:
        body = _read_json_payload()
        trigger_key = body.get("redis_key")
        if not trigger_key:
            return jsonify({"status": "skipped", "reason": "redis_key missing"}), 200

        trigger_data = r.get(trigger_key)
        if not trigger_data:
            return jsonify({"status": "skipped", "reason": "key expired"}), 200

        game_state = {}
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match="event:*", count=100)
            for key in keys:
                value = r.get(key)
                if value:
                    game_state[key] = json.loads(value)
            if cursor == 0:
                break

        snapshot = {
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "trigger_key": trigger_key,
            "trigger_event": json.loads(trigger_data),
            "game_state": game_state,
            "event_count": len(game_state),
            "processed_by": SERVER_ID,
        }

        if not storage_client or not SNAPSHOT_BUCKET:
            raise RuntimeError("Cloud Storage not configured (SNAPSHOT_BUCKET/client)")

        now = datetime.now(timezone.utc)
        blob_name = f"snapshots/{now.strftime('%Y-%m-%d')}/{int(now.timestamp())}.json"
        bucket = storage_client.bucket(SNAPSHOT_BUCKET)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(
            json.dumps(snapshot, ensure_ascii=True),
            content_type="application/json",
        )

        return jsonify(
            {
                "status": "snapshot_saved",
                "blob": blob_name,
                "event_count": len(game_state),
            }
        ), 200
    except Exception as exc:
        logger.exception("Process failed: %s", exc)
        return jsonify({"error": "process failed", "details": str(exc)}), 500


@app.route("/data")
def data():
    state = load_initial_state()
    return jsonify({"server_id": SERVER_ID, "count": len(state), "entries": state})


@app.route("/analytics")
def analytics():
    if request.headers.get("X-Admin-Key") != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if not firestore_client:
        return jsonify({"error": "Firestore not configured"}), 503

    try:
        analytics_docs = {}
        for doc in firestore_client.collection("analytics").stream():
            analytics_docs[doc.id] = doc.to_dict()

        quota_docs = {}
        for doc in firestore_client.collection("rate_limits").stream():
            quota_docs[doc.id] = doc.to_dict()

        return jsonify(
            {
                "server_id": SERVER_ID,
                "analytics": analytics_docs,
                "quotas": quota_docs,
            }
        )
    except Exception as exc:
        logger.exception("Analytics read failed: %s", exc)
        return jsonify({"error": "analytics read failed", "details": str(exc)}), 500


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
