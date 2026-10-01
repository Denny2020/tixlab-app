import json
from datetime import UTC, datetime, timedelta

from app import kv, signing, waiting_room
from app.config import settings
from conftest import make_event


def seat_status(client, event_id):
    return {s["id"]: s["status"] for s in client.get(f"/api/events/{event_id}").json()["seats"]}


def hold(client, event, seat_index=0, queue_pass=None):
    headers = {"X-Queue-Pass": queue_pass} if queue_pass else {}
    return client.post(
        f"/api/events/{event['id']}/holds", json={"seat_id": event["seat_ids"][seat_index]}, headers=headers
    )


def book(client, event, seat_index=0, email="fan@example.com"):
    hold_id = hold(client, event, seat_index).json()["hold_id"]
    return client.post(f"/api/holds/{hold_id}/confirm", json={"name": "Fan", "email": email}).json()


def queued_emails():
    return [json.loads(m) for m in kv.client.lrange(settings.email_queue, 0, -1)]


# --- health and catalogue ---------------------------------------------------------------


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"postgres": "ok", "valkey": "ok"}


def test_list_events(client, event):
    [ev] = client.get("/api/events").json()
    assert ev["artist"] == "The Fixtures"
    assert (ev["status"], ev["sold"], ev["capacity"]) == ("on_sale", 0, 4)


def test_event_detail_has_priced_seats(client, event):
    seats = client.get(f"/api/events/{event['id']}").json()["seats"]
    assert {(s["section"], s["price_cents"], s["status"]) for s in seats} == {("Front", 5000, "available")}


def test_unknown_event_is_404(client):
    assert client.get("/api/events/999").status_code == 404


def test_api_responses_name_the_pod(client, event):
    assert client.get("/api/events").headers["X-Served-By"] == kv.POD


# --- holds and checkout -------------------------------------------------------------------


def test_hold_marks_seat_held(client, event):
    r = hold(client, event)
    assert r.status_code == 201
    assert r.json()["label"] == "A1" and r.json()["price_cents"] == 5000
    assert seat_status(client, event["id"])[event["seat_ids"][0]] == "held"


def test_second_hold_on_same_seat_conflicts(client, event):
    assert hold(client, event).status_code == 201
    assert hold(client, event).status_code == 409


def test_release_frees_seat(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    assert client.delete(f"/api/holds/{hold_id}").status_code == 204
    assert seat_status(client, event["id"])[event["seat_ids"][0]] == "available"


def test_hold_publishes_live_update(client, event):
    pubsub = kv.client.pubsub()
    pubsub.subscribe(kv.live_channel(event["id"]))
    pubsub.get_message(timeout=1)  # subscribe confirmation
    hold(client, event)
    message = pubsub.get_message(timeout=2)
    assert json.loads(message["data"]) == {"type": "seat", "seat_id": event["seat_ids"][0], "status": "held"}
    pubsub.close()


def test_confirm_issues_signed_ticket_and_email(client, event):
    ticket = book(client, event)
    assert ticket["seat"] == "A1" and ticket["name"] == "Fan"
    assert signing.verify_ticket(ticket["ticket"]) == ticket["code"]
    assert ticket["ticket_url"].endswith("/#/ticket/" + ticket["ticket"])
    assert seat_status(client, event["id"])[event["seat_ids"][0]] == "booked"
    [email] = queued_emails()
    assert email["to"] == "fan@example.com" and ticket["ticket_url"] in email["body"]


def test_bots_get_no_email(client, event):
    book(client, event, email=f"bot-1@{settings.bot_email_domain}")
    assert queued_emails() == []


def test_booked_seat_cannot_be_held(client, event):
    book(client, event)
    assert hold(client, event).status_code == 409


def test_expired_hold_cannot_confirm(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    kv.client.delete(f"tixlab:holdid:{hold_id}")  # simulate TTL expiry
    r = client.post(f"/api/holds/{hold_id}/confirm", json={"name": "Fan", "email": "fan@example.com"})
    assert r.status_code == 404


def test_invalid_email_rejected(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    r = client.post(f"/api/holds/{hold_id}/confirm", json={"name": "Fan", "email": "nope"})
    assert r.status_code == 422


# --- drops and the waiting room ---------------------------------------------------------


def test_no_holds_before_the_drop_opens(client):
    ev = make_event(opens_at=datetime.now(UTC) + timedelta(minutes=5))
    assert client.get("/api/events").json()[0]["status"] == "upcoming"
    assert hold(client, ev).status_code == 403


def test_waiting_room_gates_holds(client):
    ev = make_event(opens_at=datetime.now(UTC) - timedelta(seconds=1), waiting_room=True)
    assert hold(client, ev).status_code == 403  # no pass

    queue_id = client.post(f"/api/events/{ev['id']}/queue").json()["queue_id"]
    status = client.get(f"/api/events/{ev['id']}/queue/{queue_id}").json()
    assert status["admitted"] and status["ahead"] == 0
    assert hold(client, ev, queue_pass=status["queue_pass"]).status_code == 201


def test_waiting_room_before_open(client):
    ev = make_event(opens_at=datetime.now(UTC) + timedelta(minutes=5), waiting_room=True)
    queue_id = client.post(f"/api/events/{ev['id']}/queue").json()["queue_id"]
    status = client.get(f"/api/events/{ev['id']}/queue/{queue_id}").json()
    assert not status["admitted"] and status["queue_pass"] is None
    assert 290 < status["opens_in"] <= 300


def test_queue_pass_is_bound_to_its_event(client):
    a = make_event(opens_at=datetime.now(UTC) - timedelta(seconds=1), waiting_room=True)
    b = make_event(opens_at=datetime.now(UTC) - timedelta(seconds=1), waiting_room=True)
    pass_for_a, _ = signing.queue_pass(a["id"], "someone")
    assert hold(client, b, queue_pass=pass_for_a).status_code == 403
    assert hold(client, b, queue_pass=pass_for_a[:-2] + "AA").status_code == 403


def test_admission_grows_with_time():
    opens = datetime(2030, 1, 1, tzinfo=UTC)
    assert waiting_room.admitted_count(opens, opens - timedelta(seconds=1)) == 0
    assert waiting_room.admitted_count(opens, opens) == settings.admit_batch
    assert waiting_room.admitted_count(opens, opens + timedelta(seconds=10)) == settings.admit_batch + int(
        10 * settings.admit_per_second
    )


# --- tickets ------------------------------------------------------------------------


def test_ticket_page_and_qr(client, event):
    ticket = book(client, event)
    assert client.get(f"/api/tickets/{ticket['ticket']}").json()["code"] == ticket["code"]
    qr = client.get(f"/api/tickets/{ticket['ticket']}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")
    assert qr.text.startswith("<svg")


def test_forged_ticket_rejected(client, event):
    ticket = book(client, event)
    forged = f"TIX.{ticket['code']}.AAAAAAAAAAAAAAAAAAAAAAAA"
    assert client.get(f"/api/tickets/{forged}").status_code == 404


# --- organizer --------------------------------------------------------------------


def test_admin_requires_token(client):
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_door_checkin_is_single_use(client, event, organizer):
    ticket = book(client, event)
    first = client.post("/api/admin/checkin", json={"ticket": ticket["ticket_url"]}, headers=organizer).json()
    assert first["result"] == "valid" and first["ticket"]["checked_in_at"]
    second = client.post("/api/admin/checkin", json={"ticket": ticket["ticket"]}, headers=organizer).json()
    assert second["result"] == "already_used"
    bogus = client.post("/api/admin/checkin", json={"ticket": "TIX.DEADBEEF.AAAA"}, headers=organizer).json()
    assert bogus["result"] == "invalid"


def test_stats(client, event, organizer):
    book(client, event)
    hold(client, event, seat_index=1)
    stats = client.get("/api/admin/stats", headers=organizer).json()
    [ev] = stats["events"]
    assert (ev["sold"], ev["capacity"], ev["revenue_cents"], ev["holds"]) == (1, 4, 5000, 1)
    assert sum(stats["sales_timeline"]) == 1
    assert kv.POD in stats["pods"]


def test_drop_resets_event(client, event, organizer):
    book(client, event)
    r = client.post(
        f"/api/admin/events/{event['id']}/drop", json={"opens_in_seconds": 60, "waiting_room": True}, headers=organizer
    )
    assert r.status_code == 204
    ev = client.get(f"/api/events/{event['id']}").json()
    assert ev["status"] == "upcoming" and ev["waiting_room"] and ev["sold"] == 0


def test_rush_start_and_stop(client, event, organizer):
    r = client.post("/api/admin/rush", json={"event_id": event["id"], "bots": 50, "seconds": 60}, headers=organizer)
    assert r.status_code == 201 and r.json()["bots"] == 50
    assert client.get("/api/admin/stats", headers=organizer).json()["rush"]["event_id"] == event["id"]
    client.delete("/api/admin/rush", headers=organizer)
    assert client.get("/api/admin/stats", headers=organizer).json()["rush"] is None


def test_metrics_exposed(client, event):
    hold(client, event)
    assert 'tixlab_holds_total{result="ok"}' in client.get("/metrics/").text


def test_refuses_to_start_without_secrets(monkeypatch):
    import asyncio

    import pytest

    from app.main import app, lifespan

    monkeypatch.setattr(settings, "require_secrets", True)

    async def start():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="must be set"):
        asyncio.run(start())
