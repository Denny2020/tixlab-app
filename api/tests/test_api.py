import json

from app import holds
from app.config import settings


def seat_status(client, event_id):
    return {s["id"]: s["status"] for s in client.get(f"/api/events/{event_id}").json()["seats"]}


def hold(client, event, seat_index=0):
    return client.post(f"/api/events/{event['id']}/holds", json={"seat_id": event["seat_ids"][seat_index]})


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"postgres": "ok", "valkey": "ok"}


def test_list_events_and_seats(client, event):
    events = client.get("/api/events").json()
    assert [e["name"] for e in events] == ["Test Gig"]
    assert set(seat_status(client, event["id"]).values()) == {"available"}


def test_unknown_event_is_404(client):
    assert client.get("/api/events/999").status_code == 404


def test_hold_marks_seat_held(client, event):
    r = hold(client, event)
    assert r.status_code == 201
    assert r.json()["expires_in"] == settings.hold_ttl_seconds
    assert seat_status(client, event["id"])[event["seat_ids"][0]] == "held"


def test_second_hold_on_same_seat_conflicts(client, event):
    assert hold(client, event).status_code == 201
    assert hold(client, event).status_code == 409


def test_seat_from_other_event_is_404(client, event):
    r = client.post("/api/events/999/holds", json={"seat_id": event["seat_ids"][0]})
    assert r.status_code == 404


def test_confirm_books_seat_and_queues_email(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    r = client.post(f"/api/holds/{hold_id}/confirm", json={"email": "fan@example.com"})
    assert r.status_code == 201
    booking = r.json()
    assert booking["seat"] == "A1" and booking["event"] == "Test Gig"

    assert seat_status(client, event["id"])[event["seat_ids"][0]] == "booked"
    assert client.get(f"/api/holds/{hold_id}").status_code == 404  # hold released

    queued = json.loads(holds.client.rpop(settings.email_queue))
    assert queued["to"] == "fan@example.com"
    assert booking["code"] in queued["body"]


def test_booked_seat_cannot_be_held(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    client.post(f"/api/holds/{hold_id}/confirm", json={"email": "fan@example.com"})
    assert hold(client, event).status_code == 409


def test_expired_hold_cannot_confirm(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    holds.client.delete(f"tixlab:hold:id:{hold_id}")  # simulate TTL expiry
    r = client.post(f"/api/holds/{hold_id}/confirm", json={"email": "fan@example.com"})
    assert r.status_code == 404


def test_release_frees_seat(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    assert client.delete(f"/api/holds/{hold_id}").status_code == 204
    assert seat_status(client, event["id"])[event["seat_ids"][0]] == "available"


def test_invalid_email_rejected(client, event):
    hold_id = hold(client, event).json()["hold_id"]
    r = client.post(f"/api/holds/{hold_id}/confirm", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_metrics_exposed(client, event):
    hold(client, event)
    body = client.get("/metrics/").text
    assert 'tixlab_holds_total{result="ok"}' in body
