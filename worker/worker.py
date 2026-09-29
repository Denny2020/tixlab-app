"""TixLab email worker: moves messages from the Valkey email queue to SMTP (Mailpit in the lab).

Reliable-queue pattern: BLMOVE each message into a per-pod processing list and remove it only
after the send succeeds, so a crash or SIGTERM mid-send doesn't lose it. On startup, leftovers
from this pod's previous run go back on the queue. Failed sends are retried, then dead-lettered.
"""

import json
import logging
import os
import signal
import smtplib
import socket
import time
from email.message import EmailMessage

import valkey
from prometheus_client import Counter, Gauge, start_http_server

VALKEY_URL = os.environ.get("TIXLAB_VALKEY_URL", "redis://localhost:6379/0")
QUEUE = os.environ.get("TIXLAB_EMAIL_QUEUE", "tixlab:queue:emails")
SMTP_HOST = os.environ.get("TIXLAB_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("TIXLAB_SMTP_PORT", "1025"))
MAIL_FROM = os.environ.get("TIXLAB_MAIL_FROM", "tickets@tixlab.local")
METRICS_PORT = int(os.environ.get("TIXLAB_METRICS_PORT", "8081"))
MAX_ATTEMPTS = 5

PROCESSING = f"{QUEUE}:processing:{socket.gethostname()}"
DEAD_LETTER = f"{QUEUE}:dead"

SENT = Counter("tixlab_worker_emails_sent_total", "Emails sent")
FAILED = Counter("tixlab_worker_email_failures_total", "Failed send attempts")
DEAD = Counter("tixlab_worker_emails_dead_lettered_total", "Emails given up on")
HEARTBEAT = Gauge("tixlab_worker_last_poll_timestamp_seconds", "Last time the worker polled the queue")

log = logging.getLogger("tixlab.worker")
running = True


def stop(signum, _frame):
    global running
    log.info("received %s, finishing current message", signal.Signals(signum).name)
    running = False


def send(message: dict) -> None:
    email = EmailMessage()
    email["From"] = MAIL_FROM
    email["To"] = message["to"]
    email["Subject"] = message["subject"]
    email.set_content(message["body"])
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(email)


def handle(client: valkey.Valkey, raw: str) -> None:
    message = json.loads(raw)
    try:
        send(message)
        SENT.inc()
        log.info("sent %r to %s", message["subject"], message["to"])
    except Exception:
        FAILED.inc()
        message["attempts"] = message.get("attempts", 0) + 1
        if message["attempts"] >= MAX_ATTEMPTS:
            DEAD.inc()
            log.exception("giving up on %r after %d attempts", message["subject"], message["attempts"])
            client.lpush(DEAD_LETTER, json.dumps(message))
        else:
            log.exception("send failed (attempt %d), requeueing", message["attempts"])
            client.lpush(QUEUE, json.dumps(message))
            time.sleep(1)
    finally:
        client.lrem(PROCESSING, 1, raw)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    start_http_server(METRICS_PORT)

    client = valkey.from_url(VALKEY_URL, decode_responses=True)
    while client.lmove(PROCESSING, QUEUE, "LEFT", "RIGHT"):
        log.info("requeued a message left over from a previous run")

    log.info("consuming %s, sending via %s:%d", QUEUE, SMTP_HOST, SMTP_PORT)
    while running:
        HEARTBEAT.set_to_current_time()
        try:
            raw = client.blmove(QUEUE, PROCESSING, timeout=2, src="RIGHT", dest="LEFT")
        except valkey.ConnectionError:
            log.warning("valkey unavailable, retrying")
            time.sleep(2)
            continue
        if raw is not None:
            handle(client, raw)
    log.info("stopped")


if __name__ == "__main__":
    main()
