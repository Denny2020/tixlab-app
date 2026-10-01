"""TixLab bot rush: simulated fans that compete for seats during a drop.

Idle until the organizer starts a rush (the `tixlab:rush` key in Valkey, set via the API).
Then it runs one thread per bot against the API's public endpoints, exactly like a browser:
join the waiting room, wait for admission, hold a random free seat, think, then buy (75%)
or let it go. The load is what makes the API scale, and real fans have to beat the bots.

Every bots pod runs the requested number of bots, so 2 replicas x 50 bots = 100 fans.
"""

import json
import logging
import os
import random
import signal
import threading
import time
import urllib.error
import urllib.request
import uuid

import valkey
from prometheus_client import Counter, Gauge, start_http_server

VALKEY_URL = os.environ.get("TIXLAB_VALKEY_URL", "redis://localhost:6379/0")
API_URL = os.environ.get("TIXLAB_API_URL", "http://localhost:8000").rstrip("/")
BOT_EMAIL_DOMAIN = os.environ.get("TIXLAB_BOT_EMAIL_DOMAIN", "bots.example.com")
MAX_BOTS = int(os.environ.get("TIXLAB_BOTS_MAX", "150"))
METRICS_PORT = int(os.environ.get("TIXLAB_METRICS_PORT", "8081"))
RUSH_KEY = "tixlab:rush"

ACTIONS = Counter("tixlab_bot_actions_total", "Bot actions by outcome", ["action", "result"])
RUNNING = Gauge("tixlab_bots_running", "Bot threads currently running")

log = logging.getLogger("tixlab.bots")
shutdown = threading.Event()


class Api:
    def __init__(self, bot_id: str):
        self.bot_id = bot_id

    def call(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            API_URL + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "User-Agent": f"tixlab-bot/{self.bot_id}", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            return err.code, None


def run_bot(n: int, event_id: int, stop: threading.Event) -> None:
    api = Api(f"{os.environ.get('HOSTNAME', 'local')}-{n}")
    queue_id = queue_pass = None
    pass_expires = 0.0
    while not stop.is_set():
        try:
            status, event = api.call("GET", f"/api/events/{event_id}")
            if status != 200 or event["status"] == "sold_out":
                stop.wait(2)
                continue

            if event["waiting_room"] and (queue_pass is None or pass_expires - time.time() < 30):
                if queue_id is None:
                    status, joined = api.call("POST", f"/api/events/{event_id}/queue")
                    ACTIONS.labels("queue_join", status).inc()
                    queue_id = joined["queue_id"] if joined else None
                if queue_id:
                    status, q = api.call("GET", f"/api/events/{event_id}/queue/{queue_id}")
                    if status == 404:
                        queue_id = None  # queue was reset by a new drop
                    elif q and q["admitted"]:
                        queue_pass, pass_expires = q["queue_pass"], q["pass_expires_at"]
                if queue_pass is None:
                    stop.wait(1)
                    continue
            elif event["status"] == "upcoming":
                stop.wait(1)
                continue

            free = [s for s in event["seats"] if s["status"] == "available"]
            if not free:
                stop.wait(1)
                continue
            seat = random.choice(free)
            headers = {"X-Queue-Pass": queue_pass} if queue_pass else {}
            status, held = api.call("POST", f"/api/events/{event_id}/holds", {"seat_id": seat["id"]}, headers)
            ACTIONS.labels("hold", status).inc()
            if status == 403:
                queue_id = queue_pass = None  # pass rejected: event was reset
                continue
            if status != 201:
                stop.wait(random.uniform(0.05, 0.3))
                continue

            stop.wait(random.uniform(0.5, 3.0))  # "deciding"
            if random.random() < 0.75:
                email = f"bot-{n}-{uuid.uuid4().hex[:6]}@{BOT_EMAIL_DOMAIN}"
                status, _ = api.call(
                    "POST", f"/api/holds/{held['hold_id']}/confirm", {"name": f"Bot #{n}", "email": email}
                )
                ACTIONS.labels("buy", status).inc()
                if status != 201:  # don't leave a hold blocking the seat for 10 minutes
                    api.call("DELETE", f"/api/holds/{held['hold_id']}")
            else:
                status, _ = api.call("DELETE", f"/api/holds/{held['hold_id']}")
                ACTIONS.labels("release", status).inc()
            stop.wait(random.uniform(0.2, 1.0))
        except Exception:
            ACTIONS.labels("error", "exception").inc()
            log.debug("bot %d error", n, exc_info=True)
            stop.wait(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    signal.signal(signal.SIGINT, lambda *_: shutdown.set())
    start_http_server(METRICS_PORT)
    client = valkey.from_url(VALKEY_URL, decode_responses=True)

    current, stop, threads = None, threading.Event(), []
    log.info("waiting for a rush (max %d bots per pod, API %s)", MAX_BOTS, API_URL)
    while not shutdown.is_set():
        try:
            raw = client.get(RUSH_KEY)
        except valkey.ConnectionError:
            shutdown.wait(1)  # keep the current bots going through a Valkey blip
            continue
        rush = json.loads(raw) if raw else None
        wanted = (rush["event_id"], min(rush["bots"], MAX_BOTS)) if rush else None

        if wanted != current:
            if threads:
                stop.set()
                for t in threads:
                    t.join(timeout=15)
                log.info("rush stopped")
            stop, threads = threading.Event(), []
            if wanted:
                event_id, count = wanted
                threads = [
                    threading.Thread(target=run_bot, args=(n, event_id, stop), daemon=True)
                    for n in range(1, count + 1)
                ]
                for t in threads:
                    t.start()
                    time.sleep(0.02)  # stagger, so the first second isn't one burst
                log.info("rush started: %d bots on event %d", count, event_id)
            current = wanted
        RUNNING.set(sum(t.is_alive() for t in threads))
        shutdown.wait(1)

    stop.set()
    log.info("stopped")


if __name__ == "__main__":
    main()
