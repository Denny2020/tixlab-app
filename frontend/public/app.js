const $ = (id) => document.getElementById(id);
const state = { event: null, hold: null, timer: null, poll: null };

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

const money = (cents) => (cents / 100).toLocaleString(undefined, { style: "currency", currency: "EUR" });
const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "full", timeStyle: "short" });

async function showEvents() {
  clearInterval(state.poll);
  $("event-view").hidden = true;
  $("events-view").hidden = false;
  const events = await api("/events");
  $("events").replaceChildren(...events.map((ev) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = `#event-${ev.id}`;
    a.innerHTML = `<strong></strong><span class="muted"></span><span class="price"></span>`;
    a.children[0].textContent = ev.name;
    a.children[1].textContent = `${ev.venue} · ${when(ev.starts_at)}`;
    a.children[2].textContent = money(ev.price_cents);
    li.append(a);
    return li;
  }));
}

async function showEvent(id) {
  $("events-view").hidden = true;
  $("event-view").hidden = false;
  $("confirmation").hidden = true;
  await renderSeats(id);
  clearInterval(state.poll);
  state.poll = setInterval(() => renderSeats(id).catch(() => {}), 5000);
}

async function renderSeats(id) {
  const ev = await api(`/events/${id}`);
  state.event = ev;
  $("event-name").textContent = ev.name;
  $("event-meta").textContent = `${ev.venue} · ${when(ev.starts_at)} · ${money(ev.price_cents)}`;
  const rows = {};
  for (const seat of ev.seats) (rows[seat.label[0]] ??= []).push(seat);
  $("seats").replaceChildren(...Object.entries(rows).map(([row, seats]) => {
    const div = document.createElement("div");
    div.className = "row";
    div.append(Object.assign(document.createElement("span"), { className: "row-label", textContent: row }));
    for (const seat of seats) {
      const mine = state.hold?.seat_id === seat.id;
      const btn = document.createElement("button");
      btn.className = `seat ${mine ? "mine" : seat.status}`;
      btn.textContent = seat.label.slice(1);
      btn.title = `${seat.label} — ${mine ? "your hold" : seat.status}`;
      btn.disabled = seat.status !== "available" || Boolean(state.hold);
      btn.onclick = () => holdSeat(seat);
      div.append(btn);
    }
    return div;
  }));
}

async function holdSeat(seat) {
  showError("");
  try {
    state.hold = await api(`/events/${state.event.id}/holds`, {
      method: "POST",
      body: JSON.stringify({ seat_id: seat.id }),
    });
    $("hold-seat").textContent = seat.label;
    $("hold-panel").hidden = false;
    startTimer(state.hold.expires_in);
  } catch (err) {
    showError(err.message);
  }
  await renderSeats(state.event.id);
}

function startTimer(seconds) {
  clearInterval(state.timer);
  const end = Date.now() + seconds * 1000;
  const tick = () => {
    const left = Math.max(0, Math.round((end - Date.now()) / 1000));
    $("hold-timer").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left === 0) {
      clearHold();
      showError("Your hold expired and the seat was released.");
    }
  };
  tick();
  state.timer = setInterval(tick, 1000);
}

function clearHold() {
  clearInterval(state.timer);
  state.hold = null;
  $("hold-panel").hidden = true;
  if (state.event) renderSeats(state.event.id).catch(() => {});
}

$("confirm-form").onsubmit = async (e) => {
  e.preventDefault();
  showError("");
  try {
    const booking = await api(`/holds/${state.hold.hold_id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ email: $("email").value }),
    });
    clearHold();
    $("confirmation").hidden = false;
    $("confirmation").textContent =
      `Booked! Seat ${booking.seat} for ${booking.event}. Code ${booking.code} — confirmation email sent to ${booking.email}.`;
  } catch (err) {
    showError(err.message);
  }
};

$("release").onclick = async () => {
  if (state.hold) await api(`/holds/${state.hold.hold_id}`, { method: "DELETE" }).catch(() => {});
  clearHold();
};

function route() {
  showError("");
  const match = location.hash.match(/^#event-(\d+)$/);
  (match ? showEvent(Number(match[1])) : showEvents()).catch((err) => showError(err.message));
}

window.addEventListener("hashchange", route);
api("/version").then((v) => ($("version").textContent = v.version)).catch(() => {});
route();
