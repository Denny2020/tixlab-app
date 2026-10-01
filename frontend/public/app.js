"use strict";

/* ------------------------------------------------------------------------------------------
 * Small helpers
 * ---------------------------------------------------------------------------------------- */

const $app = document.getElementById("app");

/** Builds DOM safely (text is never parsed as HTML). Style values go through CSSOM so the
 *  strict Content-Security-Policy (no inline styles) still holds. */
function h(tag, props, ...children) {
  const el = document.createElementNS(
    tag === "svg" || props?.svg ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml",
    tag,
  );
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false || key === "svg") continue;
    if (key === "class") el.setAttribute("class", value);
    else if (key === "vars") for (const [name, v] of Object.entries(value)) el.style.setProperty(name, v);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "text") el.textContent = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

const money = (cents) =>
  (cents / 100).toLocaleString(undefined, {
    style: "currency",
    currency: "AUD",
    minimumFractionDigits: cents % 100 ? 2 : 0,
  });
const when = (iso) =>
  new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const longDate = (iso) =>
  new Date(iso).toLocaleString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const timeOf = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const d = Math.floor(seconds / 86400);
  const hms = [Math.floor((seconds % 86400) / 3600), Math.floor((seconds % 3600) / 60), seconds % 60]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
  return d ? `${d}d ${hms}` : hms;
}

function store(kind) {
  const area = kind === "session" ? sessionStorage : localStorage;
  return {
    get(key, fallback = null) {
      try {
        const v = area.getItem(key);
        return v == null ? fallback : JSON.parse(v);
      } catch {
        return fallback;
      }
    },
    set(key, value) {
      try {
        area.setItem(key, JSON.stringify(value));
      } catch {}
    },
    del(key) {
      try {
        area.removeItem(key);
      } catch {}
    },
  };
}
const session = store("session");
const local = store("local");

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", body, headers = {} } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const pod = res.headers.get("X-Served-By");
  if (pod) showServer(pod);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

const $ = (sel, root = document) => root.querySelector(sel);

let appVersion = "";
function showServer(pod) {
  $("#served").textContent = `${appVersion ? appVersion + " · " : ""}served by pod ${pod}`;
}

function toast(message, kind = "info") {
  const el = h("div", { class: `toast ${kind}`, role: "status" }, message);
  $("#toasts").append(el);
  setTimeout(() => el.classList.add("out"), 3200);
  setTimeout(() => el.remove(), 3700);
}

/* Per-view lifecycle: intervals, streams and listeners are cleaned up on navigation. */
let cleanups = [];
const onLeave = (fn) => cleanups.push(fn);
function every(ms, fn) {
  const id = setInterval(fn, ms);
  onLeave(() => clearInterval(id));
  return id;
}

/* ------------------------------------------------------------------------------------------
 * Shared pieces
 * ---------------------------------------------------------------------------------------- */

function poster(ev, size = "card") {
  return h(
    "div",
    { class: `poster poster-${size}`, vars: { "--h": ev.hue } },
    h("span", { class: "poster-genre" }, ev.genre || "Live"),
    h("span", { class: "poster-artist" }, ev.artist || ev.name),
    h("span", { class: "poster-grid", "aria-hidden": "true" }),
  );
}

function statusBadge(ev) {
  if (ev.status === "sold_out") return h("span", { class: "badge sold" }, "Sold out");
  if (ev.status === "upcoming") return h("span", { class: "badge soon" }, ev.waiting_room ? "Drop soon" : "Opens soon");
  const left = ev.capacity - ev.sold;
  if (left <= ev.capacity * 0.25) return h("span", { class: "badge hot" }, `${left} left`);
  return h("span", { class: "badge on" }, "On sale");
}

/** A live countdown element; calls onDone once when it reaches zero. */
function countdown(targetIso, onDone) {
  const el = h("span", { class: "countdown" });
  const target = new Date(targetIso).getTime();
  let done = false;
  const tick = () => {
    const left = (target - Date.now()) / 1000;
    el.textContent = duration(left);
    if (left <= 0 && !done) {
      done = true;
      onDone?.();
    }
  };
  tick();
  every(1000, tick);
  return el;
}

function saveTicket(t) {
  const tickets = local.get("tickets", []).filter((x) => x.ticket !== t.ticket);
  tickets.unshift({
    ticket: t.ticket, code: t.code, artist: t.artist, event: t.event, seat: t.seat,
    section: t.section, starts_at: t.starts_at, venue: t.venue, hue: t.hue,
  });
  local.set("tickets", tickets.slice(0, 50));
}

/* ------------------------------------------------------------------------------------------
 * Home
 * ---------------------------------------------------------------------------------------- */

async function viewHome() {
  const events = await api("/events");
  const featured =
    events.find((e) => e.waiting_room && e.status === "upcoming") ||
    events.find((e) => e.waiting_room && e.status === "on_sale") ||
    events[0];

  const hero = featured
    ? h(
        "section",
        { class: "hero", vars: { "--h": featured.hue } },
        poster(featured, "hero"),
        h(
          "div",
          { class: "hero-copy" },
          h("p", { class: "eyebrow" }, featured.waiting_room ? "Featured drop" : "Featured"),
          h("h1", {}, featured.artist),
          h("p", { class: "hero-name" }, featured.name),
          h("p", { class: "muted" }, `${when(featured.starts_at)} · ${featured.venue}`),
          h("p", { class: "hero-tagline" }, featured.tagline),
          featured.status === "upcoming"
            ? h("div", { class: "hero-timer" }, h("span", { class: "muted" }, "Drop opens in"), countdown(featured.opens_at, () => route()))
            : h("div", { class: "hero-timer" }, statusBadge(featured), h("span", { class: "muted" }, `${featured.capacity - featured.sold} of ${featured.capacity} seats left`)),
          h("a", { class: "button big", href: `#/e/${featured.id}` }, featured.status === "upcoming" ? "Get in line" : "Get tickets"),
        ),
      )
    : h("p", {}, "No events yet.");

  const cards = events.map((ev) =>
    h(
      "a",
      { class: "card", href: `#/e/${ev.id}`, vars: { "--h": ev.hue } },
      poster(ev),
      h(
        "div",
        { class: "card-body" },
        h("div", { class: "card-top" }, statusBadge(ev), h("span", { class: "price" }, `from ${money(ev.price_cents)}`)),
        h("h3", {}, ev.name),
        h("p", { class: "muted" }, `${when(ev.starts_at)}`),
        h("p", { class: "muted small" }, ev.venue),
        h("div", { class: "meter", "aria-hidden": "true" }, h("span", { vars: { "--p": `${(100 * ev.sold) / (ev.capacity || 1)}%` } })),
      ),
    ),
  );

  $app.replaceChildren(hero, h("h2", { class: "section-title" }, "All events"), h("div", { class: "grid" }, cards));
}

/* ------------------------------------------------------------------------------------------
 * Event page: waiting room, live seat map, checkout
 * ---------------------------------------------------------------------------------------- */

async function viewEvent(id) {
  const ev = await api(`/events/${id}`);
  const state = { ev, hold: session.get(`hold:${id}`), seatEls: new Map(), feed: [] };

  const passKey = `pass:${id}`;
  const queueKey = `queue:${id}`;
  const havePass = () => {
    const p = session.get(passKey);
    return p && p.expires * 1000 > Date.now() + 5000;
  };
  const canPick = () =>
    state.ev.status === "on_sale" && (!state.ev.waiting_room || havePass()) && !state.hold;

  // --- header
  const left = h("span", { class: "stat-num" });
  const header = h(
    "section",
    { class: "event-hero", vars: { "--h": ev.hue } },
    poster(ev, "banner"),
    h(
      "div",
      { class: "event-copy" },
      h("p", { class: "eyebrow" }, `${ev.genre} · ${ev.venue}`),
      h("h1", {}, ev.artist),
      h("p", { class: "hero-name" }, ev.name),
      h("p", { class: "muted" }, `${longDate(ev.starts_at)} · doors ${timeOf(ev.starts_at)}`),
      h("p", { class: "event-desc" }, ev.description),
      h("div", { class: "event-stats" }, h("div", {}, left, h("span", { class: "muted" }, "seats left")), h("div", {}, h("span", { class: "stat-num" }, money(ev.price_cents)), h("span", { class: "muted" }, "from"))),
    ),
  );

  // --- seat map
  const sections = [...new Set(ev.seats.map((s) => s.section))];
  const sectionIndex = Object.fromEntries(sections.map((s, i) => [s, i]));
  const rows = {};
  for (const seat of ev.seats) (rows[seat.label[0]] ??= []).push(seat);

  const map = h(
    "div",
    { class: "seatmap" },
    h("div", { class: "stage" }, h("span", {}, "STAGE")),
    Object.entries(rows).map(([row, seats]) =>
      h(
        "div",
        { class: "seat-row" },
        h("span", { class: "row-label" }, row),
        seats.map((seat, i) => {
          const btn = h(
            "button",
            {
              class: "seat",
              vars: { "--s": sectionIndex[seat.section] },
              title: `${seat.label} · ${seat.section} · ${money(seat.price_cents)}`,
              "aria-label": `Seat ${seat.label}, ${seat.section}, ${money(seat.price_cents)}`,
              onclick: () => pick(seat),
            },
            seat.label.slice(1),
          );
          state.seatEls.set(seat.id, { el: btn, seat });
          return i === Math.floor(seats.length / 2) - 1 ? [btn, h("span", { class: "aisle" })] : btn;
        }),
        h("span", { class: "row-label" }, row),
      ),
    ),
  );
  const legend = h(
    "div",
    { class: "legend" },
    sections.map((name) => {
      const price = ev.seats.find((s) => s.section === name).price_cents;
      return h("span", {}, h("i", { class: "dot", vars: { "--s": sectionIndex[name] } }), `${name} ${money(price)}`);
    }),
    h("span", {}, h("i", { class: "dot held" }), "held"),
    h("span", {}, h("i", { class: "dot booked" }), "sold"),
  );
  const feed = h("ul", { class: "feed", "aria-live": "polite" });
  const mapCard = h("section", { class: "panel map-card", vars: { "--h": ev.hue } }, h("div", { class: "panel-head" }, h("h2", {}, "Seat map"), h("span", { class: "live-dot" }, "LIVE")), map, legend, feed);

  const side = h("aside", { class: "panel side", vars: { "--h": ev.hue } });

  function paintSeat(seatId, status) {
    const entry = state.seatEls.get(seatId);
    if (!entry) return;
    entry.seat.status = status;
    const mine = state.hold?.seat_id === seatId;
    entry.el.className = `seat ${mine ? "mine" : status}`;
    entry.el.disabled = !mine && (status !== "available" || !canPick());
  }
  function paintAll() {
    for (const [id, { seat }] of state.seatEls) paintSeat(id, seat.status);
    left.textContent = [...state.seatEls.values()].filter((e) => e.seat.status !== "booked").length;
    map.classList.toggle("locked", !canPick() && !state.hold);
  }

  function addFeed(text) {
    state.feed.unshift({ text, at: Date.now() });
    state.feed = state.feed.slice(0, 4);
    feed.replaceChildren(...state.feed.map((f) => h("li", {}, f.text)));
  }

  // --- live updates
  const stream = new EventSource(`/api/live/events/${id}`);
  onLeave(() => stream.close());
  stream.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "reset") {
      session.del(passKey);
      session.del(queueKey);
      session.del(`hold:${id}`);
      toast("The organizer reset this drop", "warn");
      route();
      return;
    }
    if (data.type !== "seat") return;
    const entry = state.seatEls.get(data.seat_id);
    if (!entry) return;
    if (data.status === "booked" && state.hold?.seat_id !== data.seat_id) addFeed(`Seat ${entry.seat.label} just sold`);
    if (state.hold?.seat_id === data.seat_id && data.status === "available") return; // our own release
    paintSeat(data.seat_id, data.status);
    paintAll();
  };

  // --- side panel states
  function renderSide() {
    cleanupSide();
    if (state.hold) return renderCheckout();
    if (state.ev.status === "sold_out") {
      return side.replaceChildren(h("h2", {}, "Sold out"), h("p", { class: "muted" }, "Every seat is gone. Follow the artist for the next drop."));
    }
    if (state.ev.waiting_room && !havePass()) return renderQueue();
    if (state.ev.status === "upcoming") {
      return side.replaceChildren(
        h("p", { class: "eyebrow" }, "Sales open in"),
        h("div", { class: "big-timer" }, countdown(state.ev.opens_at, refresh)),
        h("p", { class: "muted" }, `on ${when(state.ev.opens_at)}`),
      );
    }
    side.replaceChildren(
      h("p", { class: "eyebrow" }, state.ev.waiting_room ? "You're in!" : "On sale"),
      h("h2", {}, "Pick a seat"),
      h("p", { class: "muted" }, "Tap any open seat on the map. It's yours for 10 minutes while you check out."),
      state.ev.waiting_room ? h("p", { class: "note" }, "Your waiting-room pass is valid for 15 minutes.") : null,
    );
  }

  let sideTimers = [];
  function cleanupSide() {
    sideTimers.forEach(clearInterval);
    sideTimers = [];
  }
  onLeave(cleanupSide);

  function renderQueue() {
    const queueId = session.get(queueKey);
    if (!queueId) {
      side.replaceChildren(
        h("p", { class: "eyebrow" }, state.ev.status === "upcoming" ? "Drop opens in" : "Drop is live"),
        state.ev.status === "upcoming" ? h("div", { class: "big-timer" }, countdown(state.ev.opens_at)) : null,
        h("h2", {}, "Virtual waiting room"),
        h("p", { class: "muted" }, "Everyone who joins gets a fair place in line. When the drop opens, fans are let in a few at a time."),
        h(
          "button",
          {
            class: "button big",
            onclick: async (e) => {
              e.target.disabled = true;
              try {
                const { queue_id } = await api(`/events/${id}/queue`, { method: "POST" });
                session.set(queueKey, queue_id);
                renderSide();
              } catch (err) {
                toast(err.message, "error");
                e.target.disabled = false;
              }
            },
          },
          "Join the waiting room",
        ),
      );
      return;
    }
    const ahead = h("div", { class: "queue-num" }, "…");
    const bar = h("span", {});
    const meta = h("p", { class: "muted" });
    const timer = h("p", { class: "muted" });
    side.replaceChildren(
      h("p", { class: "eyebrow pulse" }, "You're in line"),
      ahead,
      h("p", { class: "muted" }, "fans ahead of you"),
      h("div", { class: "meter big" }, bar),
      meta,
      timer,
      h("p", { class: "note" }, "Keep this tab open. You'll be moved to seat selection automatically."),
    );
    let firstAhead = null;
    const poll = async () => {
      try {
        const q = await api(`/events/${id}/queue/${queueId}`);
        if (q.admitted) {
          session.set(passKey, { token: q.queue_pass, expires: q.pass_expires_at });
          toast("You're in! Pick your seats.", "success");
          await refresh();
          return;
        }
        firstAhead ??= Math.max(q.ahead, 1);
        ahead.textContent = q.ahead.toLocaleString();
        bar.style.setProperty("--p", `${100 - (100 * q.ahead) / firstAhead}%`);
        meta.textContent = `${q.queue_length.toLocaleString()} fans in the waiting room`;
        timer.textContent = q.opens_in > 0 ? `Drop opens in ${duration(q.opens_in)}` : "Drop is live. Letting fans in now";
      } catch (err) {
        if (err.status === 404) {
          session.del(queueKey);
          renderSide();
        }
      }
    };
    poll();
    sideTimers.push(setInterval(poll, 1000));
  }

  function renderCheckout() {
    const hold = state.hold;
    const total = 600;
    const ring = h("circle", { svg: true, cx: 50, cy: 50, r: 44, class: "ring-fg", pathLength: 100 });
    const remaining = h("span", { class: "ring-text" });
    const name = h("input", { type: "text", placeholder: "Your name", required: true, maxlength: 120, autocomplete: "name" });
    const email = h("input", { type: "email", placeholder: "you@example.com", required: true, autocomplete: "email" });
    const buy = h("button", { class: "button big", type: "submit" }, `Buy · ${money(hold.price_cents)}`);
    const end = Date.now() + hold.expires_in * 1000;
    const tick = () => {
      const s = (end - Date.now()) / 1000;
      remaining.textContent = duration(s).replace(/^00:/, "");
      ring.style.setProperty("--p", Math.max(0, (100 * s) / total));
      if (s <= 0) {
        toast("Your hold expired and the seat was released", "warn");
        clearHold();
      }
    };
    side.replaceChildren(
      h("p", { class: "eyebrow" }, "Seat held"),
      h(
        "div",
        { class: "hold-head" },
        h("div", {}, h("div", { class: "seat-big" }, hold.label), h("p", { class: "muted" }, `${hold.section} · ${money(hold.price_cents)}`)),
        h("div", { class: "ring" }, h("svg", { viewBox: "0 0 100 100" }, h("circle", { svg: true, cx: 50, cy: 50, r: 44, class: "ring-bg" }), ring), remaining),
      ),
      h(
        "form",
        {
          class: "checkout",
          onsubmit: async (e) => {
            e.preventDefault();
            buy.disabled = true;
            try {
              const ticket = await api(`/holds/${hold.hold_id}/confirm`, {
                method: "POST",
                body: { name: name.value, email: email.value },
              });
              session.del(`hold:${id}`);
              saveTicket(ticket);
              location.hash = `#/ticket/${ticket.ticket}?new=1`;
            } catch (err) {
              toast(err.message, "error");
              buy.disabled = false;
              if (err.status === 404 || err.status === 409) clearHold();
            }
          },
        },
        h("label", {}, "Name on ticket", name),
        h("label", {}, "Email for your ticket", email),
        buy,
        h(
          "button",
          {
            type: "button",
            class: "button ghost",
            onclick: async () => {
              await api(`/holds/${hold.hold_id}`, { method: "DELETE" }).catch(() => {});
              clearHold();
            },
          },
          "Release seat",
        ),
      ),
    );
    tick();
    sideTimers.push(setInterval(tick, 1000));
  }

  function clearHold() {
    const seatId = state.hold?.seat_id;
    state.hold = null;
    session.del(`hold:${id}`);
    if (seatId) paintSeat(seatId, "available");
    paintAll();
    renderSide();
  }

  async function pick(seat) {
    if (!canPick() || seat.status !== "available") return;
    const pass = session.get(passKey);
    try {
      const hold = await api(`/events/${id}/holds`, {
        method: "POST",
        body: { seat_id: seat.id },
        headers: pass ? { "X-Queue-Pass": pass.token } : {},
      });
      state.hold = hold;
      session.set(`hold:${id}`, hold);
      paintAll();
      renderSide();
    } catch (err) {
      if (err.status === 409) {
        paintSeat(seat.id, "held");
        state.seatEls.get(seat.id).el.classList.add("shake");
        toast("Too slow! Someone just grabbed that seat", "warn");
      } else if (err.status === 403) {
        session.del(passKey);
        toast(err.message, "warn");
        refresh();
      } else toast(err.message, "error");
    }
  }

  async function refresh() {
    try {
      const fresh = await api(`/events/${id}`);
      state.ev = fresh;
      for (const s of fresh.seats) {
        const entry = state.seatEls.get(s.id);
        if (entry) entry.seat.status = s.status;
      }
    } catch {}
    if (state.hold) {
      // the hold may have expired while we were away
      await api(`/holds/${state.hold.hold_id}`).then(
        (held) => (state.hold = held),
        () => (state.hold = null),
      );
    }
    paintAll();
    renderSide();
  }

  $app.replaceChildren(header, h("div", { class: "event-layout" }, mapCard, side));
  await refresh();
}

/* ------------------------------------------------------------------------------------------
 * Tickets
 * ---------------------------------------------------------------------------------------- */

async function viewTicket(token, params) {
  const t = await api(`/tickets/${encodeURIComponent(token)}`);
  saveTicket(t);
  const fresh = params.get("new");
  $app.replaceChildren(
    fresh ? h("div", { class: "celebrate" }, h("h1", {}, "You're going! 🎉"), h("p", { class: "muted" }, `We've emailed your ticket to ${t.email}.`)) : null,
    h(
      "article",
      { class: "ticket", vars: { "--h": t.hue } },
      h(
        "div",
        { class: "ticket-main" },
        h("p", { class: "eyebrow" }, "Admit one"),
        h("h1", {}, t.artist),
        h("p", { class: "hero-name" }, t.event),
        h(
          "dl",
          { class: "ticket-facts" },
          h("div", {}, h("dt", {}, "Date"), h("dd", {}, longDate(t.starts_at))),
          h("div", {}, h("dt", {}, "Doors"), h("dd", {}, timeOf(t.starts_at))),
          h("div", {}, h("dt", {}, "Venue"), h("dd", {}, t.venue)),
          h("div", {}, h("dt", {}, "Section"), h("dd", {}, t.section)),
          h("div", {}, h("dt", {}, "Seat"), h("dd", { class: "seat-big" }, t.seat)),
          h("div", {}, h("dt", {}, "Name"), h("dd", {}, t.name)),
        ),
      ),
      h(
        "div",
        { class: "ticket-stub" },
        h("img", { class: "qr", src: `/api/tickets/${encodeURIComponent(token)}/qr.svg`, alt: `QR code for ticket ${t.code}`, width: 180, height: 180 }),
        h("code", {}, t.code),
        t.checked_in_at
          ? h("span", { class: "badge on" }, `Checked in ${timeOf(t.checked_in_at)}`)
          : h("span", { class: "muted small" }, "Show this at the door"),
      ),
    ),
    h(
      "div",
      { class: "actions" },
      h("a", { class: "button ghost", href: `#/e/${t.event_id}` }, "Back to event"),
      h(
        "button",
        {
          class: "button ghost",
          onclick: () => navigator.clipboard?.writeText(t.ticket_url).then(() => toast("Ticket link copied", "success")),
        },
        "Copy ticket link",
      ),
    ),
  );
}

function viewMyTickets() {
  const tickets = local.get("tickets", []);
  $app.replaceChildren(
    h("h1", { class: "page-title" }, "My tickets"),
    tickets.length
      ? h(
          "div",
          { class: "grid" },
          tickets.map((t) =>
            h(
              "a",
              { class: "card", href: `#/ticket/${t.ticket}`, vars: { "--h": t.hue } },
              poster({ ...t, genre: t.section }),
              h("div", { class: "card-body" }, h("h3", {}, t.event), h("p", { class: "muted" }, when(t.starts_at)), h("p", {}, `Seat ${t.seat} · ${t.code}`)),
            ),
          ),
        )
      : h("p", { class: "muted" }, "No tickets yet. ", h("a", { href: "#/" }, "Find an event")),
  );
}

/* ------------------------------------------------------------------------------------------
 * Organizer dashboard
 * ---------------------------------------------------------------------------------------- */

async function viewOrganizer() {
  const token = session.get("organizerToken");
  if (!token) return organizerLogin();
  const auth = { Authorization: `Bearer ${token}` };
  const admin = (path, opts = {}) => api(`/admin${path}`, { ...opts, headers: auth });

  let stats;
  try {
    stats = await admin("/stats");
  } catch (err) {
    if (err.status === 401) return organizerLogin("That token didn't work");
    throw err;
  }

  const kpis = h("div", { class: "kpis" });
  const spark = h("div", { class: "spark" });
  const pods = h("div", { class: "pods" });
  const table = h("div", { class: "event-table" });

  // bot rush controls (static, so typing isn't interrupted by refreshes)
  const rushEvent = h("select", {}, stats.events.map((e) => h("option", { value: e.id }, `${e.artist}: ${e.name}`)));
  const rushBots = h("input", { type: "range", min: 10, max: 300, step: 10, value: 100 });
  const rushBotsLabel = h("strong", {}, "100");
  rushBots.addEventListener("input", () => (rushBotsLabel.textContent = rushBots.value));
  const rushSeconds = h("select", {}, [60, 120, 300].map((s) => h("option", { value: s }, `${s / 60} min`)));
  const rushState = h("p", { class: "muted" });
  const rushBtn = h("button", { class: "button danger" }, "Start bot rush");
  rushBtn.addEventListener("click", async () => {
    try {
      if (stats.rush) await admin("/rush", { method: "DELETE" });
      else
        await admin("/rush", {
          method: "POST",
          body: { event_id: Number(rushEvent.value), bots: Number(rushBots.value), seconds: Number(rushSeconds.value) },
        });
      await refresh();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // door check-in
  const doorInput = h("input", { type: "text", placeholder: "Paste ticket link or TIX.… code", autocomplete: "off" });
  const doorResult = h("div", { class: "door-result" });
  async function checkin(value) {
    if (!value.trim()) return;
    try {
      const r = await admin("/checkin", { method: "POST", body: { ticket: value } });
      const label = { valid: "VALID: let them in", already_used: "ALREADY USED", invalid: "INVALID TICKET" }[r.result];
      doorResult.className = `door-result ${r.result}`;
      doorResult.replaceChildren(
        h("strong", {}, label),
        r.ticket ? h("span", {}, `${r.ticket.name} · ${r.ticket.seat} (${r.ticket.section}) · ${r.ticket.event}`) : null,
        r.result === "already_used" && r.ticket ? h("span", { class: "muted" }, `first scanned at ${timeOf(r.ticket.checked_in_at)}`) : null,
      );
      doorInput.value = "";
    } catch (err) {
      toast(err.message, "error");
    }
  }
  const doorForm = h(
    "form",
    { class: "door-form", onsubmit: (e) => (e.preventDefault(), checkin(doorInput.value)) },
    doorInput,
    h("button", { class: "button" }, "Check in"),
  );
  const camera = "BarcodeDetector" in window && window.isSecureContext ? scannerButton(checkin) : h("p", { class: "note" }, "Camera scanning needs HTTPS or localhost. Paste the ticket link instead.");

  function render() {
    const totals = stats.events.reduce(
      (t, e) => ({ sold: t.sold + e.sold, revenue: t.revenue + e.revenue_cents, queue: t.queue + e.queue, holds: t.holds + e.holds, inside: t.inside + e.checked_in }),
      { sold: 0, revenue: 0, queue: 0, holds: 0, inside: 0 },
    );
    kpis.replaceChildren(
      kpi("Tickets sold", totals.sold.toLocaleString()),
      kpi("Revenue", money(totals.revenue)),
      kpi("In waiting rooms", totals.queue.toLocaleString()),
      kpi("Seats on hold", totals.holds.toLocaleString()),
      kpi("Checked in", totals.inside.toLocaleString()),
    );

    const max = Math.max(1, ...stats.sales_timeline);
    spark.replaceChildren(
      h(
        "svg",
        { viewBox: `0 0 ${stats.sales_timeline.length * 10} 60`, preserveAspectRatio: "none", role: "img", "aria-label": "Tickets sold per 10 seconds, last 5 minutes" },
        stats.sales_timeline.map((n, i) =>
          h("rect", { svg: true, x: i * 10 + 1, y: 60 - (56 * n) / max, width: 8, height: Math.max(1, (56 * n) / max), rx: 1.5 }),
        ),
      ),
      h("div", { class: "spark-axis" }, h("span", {}, "5 min ago"), h("span", {}, `peak ${max * 6}/min`), h("span", {}, "now")),
    );

    pods.replaceChildren(
      h("div", { class: "pods-count" }, h("span", { class: "stat-num" }, stats.pods.length), h("span", { class: "muted" }, stats.pods.length === 1 ? "API pod serving" : "API pods serving")),
      h("div", { class: "pod-chips" }, stats.pods.map((p) => h("span", { class: "pod" }, p))),
    );

    table.replaceChildren(
      ...stats.events.map((e) =>
        h(
          "div",
          { class: "event-row" },
          h("div", { class: "er-name" }, h("strong", {}, e.artist), h("span", { class: "muted small" }, e.name), statusBadge(e)),
          h("div", { class: "er-sold" }, h("div", { class: "meter" }, h("span", { vars: { "--p": `${(100 * e.sold) / (e.capacity || 1)}%` } })), h("span", { class: "small" }, `${e.sold}/${e.capacity} sold · ${money(e.revenue_cents)}`)),
          h(
            "div",
            { class: "er-live small muted" },
            e.waiting_room ? `${e.queue} in queue · ${e.admitted} admitted` : "no waiting room",
            h("br"),
            `${e.holds} holds · ${e.checked_in} checked in`,
            e.status === "upcoming" ? [h("br"), "opens in ", countdownText(e.opens_at)] : null,
          ),
          h(
            "div",
            { class: "er-actions" },
            h("button", { class: "button small", onclick: () => drop(e, 60, true) }, "Drop in 60s"),
            h("button", { class: "button small ghost", onclick: () => drop(e, 0, e.waiting_room) }, "Reset & open"),
          ),
        ),
      ),
    );

    rushBtn.textContent = stats.rush ? "Stop bot rush" : "Start bot rush";
    rushBtn.classList.toggle("running", Boolean(stats.rush));
    rushState.textContent = stats.rush
      ? `🤖 ${stats.rush.bots} bots per pod rushing ${stats.events.find((e) => e.id === stats.rush.event_id)?.artist ?? "event"}: ${stats.rush.ends_in}s left`
      : "Bots act like real fans: queue, grab seats, hesitate, buy. Watch the API scale.";
  }

  async function drop(e, seconds, waitingRoom) {
    if (!confirm(`Reset "${e.name}"? This deletes its ${e.sold} bookings.`)) return;
    try {
      await admin(`/events/${e.id}/drop`, { method: "POST", body: { opens_in_seconds: seconds, waiting_room: waitingRoom } });
      toast(seconds ? `Drop scheduled in ${seconds}s` : "Event reset and open", "success");
      await refresh();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function refresh() {
    try {
      stats = await admin("/stats");
      render();
    } catch (err) {
      if (err.status === 401) organizerLogin("Session expired");
    }
  }

  $app.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { class: "page-title" }, "Organizer"), h("button", { class: "button ghost small", onclick: () => (session.del("organizerToken"), route()) }, "Sign out")),
    kpis,
    h(
      "div",
      { class: "org-grid" },
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Sales"), h("span", { class: "live-dot" }, "LIVE")), spark),
      h("section", { class: "panel" }, h("h2", {}, "Platform"), pods),
      h(
        "section",
        { class: "panel rush" },
        h("h2", {}, "Bot rush"),
        h("label", {}, "Target event", rushEvent),
        h("label", {}, h("span", {}, "Bots per pod: ", rushBotsLabel), rushBots),
        h("label", {}, "Duration", rushSeconds),
        rushBtn,
        rushState,
      ),
      h("section", { class: "panel door" }, h("h2", {}, "Door check-in"), doorForm, camera, doorResult),
    ),
    h("section", { class: "panel" }, h("h2", {}, "Events"), table),
  );
  render();
  every(1000, refresh);
}

function kpi(label, value) {
  return h("div", { class: "kpi" }, h("span", { class: "muted small" }, label), h("strong", {}, value));
}

function countdownText(iso) {
  return duration((new Date(iso).getTime() - Date.now()) / 1000);
}

function scannerButton(onCode) {
  const video = h("video", { playsinline: true, muted: true, class: "scanner", hidden: true });
  const btn = h("button", { class: "button ghost", type: "button" }, "Scan with camera");
  btn.addEventListener("click", async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    onLeave(() => stream.getTracks().forEach((t) => t.stop()));
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
    const detector = new BarcodeDetector({ formats: ["qr_code"] });
    let last = "";
    every(400, async () => {
      const [code] = await detector.detect(video).catch(() => []);
      if (code && code.rawValue !== last) {
        last = code.rawValue;
        onCode(code.rawValue);
      }
    });
  });
  return h("div", {}, btn, video);
}

function organizerLogin(error) {
  session.del("organizerToken");
  const input = h("input", { type: "password", placeholder: "Organizer token", required: true, autocomplete: "current-password" });
  $app.replaceChildren(
    h(
      "section",
      { class: "panel login" },
      h("h1", {}, "Organizer sign in"),
      h("p", { class: "muted" }, "Dashboard, door check-in, drops and the bot rush."),
      error ? h("p", { class: "error" }, error) : null,
      h(
        "form",
        { onsubmit: (e) => (e.preventDefault(), session.set("organizerToken", input.value.trim()), route()) },
        input,
        h("button", { class: "button big" }, "Sign in"),
      ),
    ),
  );
}

/* ------------------------------------------------------------------------------------------
 * Router
 * ---------------------------------------------------------------------------------------- */

async function route() {
  cleanups.forEach((fn) => fn());
  cleanups = [];
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean);
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === (parts[0] || "home") || (parts[0] === "e" && a.dataset.nav === "home")));
  window.scrollTo(0, 0);
  try {
    if (parts[0] === "e" && parts[1]) await viewEvent(Number(parts[1]));
    else if (parts[0] === "ticket" && parts[1]) await viewTicket(parts[1], params);
    else if (parts[0] === "tickets") viewMyTickets();
    else if (parts[0] === "organizer") await viewOrganizer();
    else await viewHome();
  } catch (err) {
    $app.replaceChildren(h("section", { class: "panel" }, h("h1", {}, "Something went wrong"), h("p", { class: "muted" }, err.message), h("a", { class: "button", href: "#/" }, "Back to events")));
  }
}

window.addEventListener("hashchange", route);
api("/version").then((v) => ((appVersion = v.version), showServer(v.pod))).catch(() => {});
route();
