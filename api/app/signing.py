"""HMAC-signed tokens for tickets and waiting-room passes.

Tickets:      TIX.<code>.<sig>              (printed as a QR code, checked at the door)
Queue passes: QP.<event>.<queue_id>.<exp>.<sig>
"""

import base64
import hashlib
import hmac
import time

from .config import settings


def _sig(message: str) -> str:
    mac = hmac.new(settings.signing_key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b32encode(mac[:15]).decode().rstrip("=")


def ticket_token(code: str) -> str:
    return f"TIX.{code}.{_sig('ticket:' + code)}"


def verify_ticket(token: str) -> str | None:
    """Returns the booking code if the token is genuine."""
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != "TIX":
        return None
    code, sig = parts[1], parts[2]
    return code if hmac.compare_digest(sig, _sig("ticket:" + code)) else None


def queue_pass(event_id: int, queue_id: str) -> tuple[str, int]:
    expires = int(time.time()) + settings.queue_pass_ttl_seconds
    body = f"{event_id}.{queue_id}.{expires}"
    return f"QP.{body}.{_sig('pass:' + body)}", expires


def verify_queue_pass(token: str | None, event_id: int) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != "QP":
        return False
    _, ev, queue_id, expires, sig = parts
    body = f"{ev}.{queue_id}.{expires}"
    return (
        hmac.compare_digest(sig, _sig("pass:" + body))
        and ev == str(event_id)
        and int(expires) > time.time()
    )
