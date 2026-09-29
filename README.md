# TixLab app

Event ticketing app used to practise a production-style Kubernetes delivery pipeline
(CI → signed images → GitOps → guardrails → canary → observability).
Deployment manifests live in the separate `tixlab-gitops` repo.

## Components

| Image | What it does |
|---|---|
| `tixlab-api` | FastAPI: list events, hold a seat (Valkey, 10-min TTL), confirm a booking (Postgres). Also runs migrations (`alembic upgrade head`) and jobs (`python -m app.jobs seed\|report`). |
| `tixlab-worker` | Takes emails off the Valkey queue and sends them over SMTP (Mailpit in the lab). Doesn't lose messages on SIGTERM; retries 5 times, then dead-letters. |
| `tixlab-frontend` | Static HTML/JS on unprivileged nginx (port 8080). |

Double booking is prevented by a unique constraint on `bookings.seat_id`; the Valkey hold is only a
reservation. Expired holds release themselves through the TTL, so no cleanup job is needed.

## Run locally

```bash
docker compose up --build        # UI http://localhost:8088 · API docs http://localhost:8000/docs · Mailpit http://localhost:8025
docker compose run --rm --build api-test   # tests against real Postgres + Valkey
docker compose exec api python -m app.jobs report   # queue a sales report email
docker compose down -v           # stop and wipe data
```

## API

| Method | Path | |
|---|---|---|
| GET | `/api/events` | list events |
| GET | `/api/events/{id}` | event with seat map (`available` / `held` / `booked`) |
| POST | `/api/events/{id}/holds` | `{"seat_id": n}` → hold (409 if held or booked) |
| GET / DELETE | `/api/holds/{hold_id}` | inspect / release a hold |
| POST | `/api/holds/{hold_id}/confirm` | `{"email": "..."}` → booking, confirmation email queued |
| GET | `/api/version` | running version (`TIXLAB_VERSION`, set to the image tag in-cluster) |
| GET | `/healthz`, `/readyz` | liveness (process only) / readiness (Postgres + Valkey) |
| GET | `/metrics` | Prometheus metrics (worker exposes its own on `:8081`) |

## Configuration

All settings are `TIXLAB_*` environment variables: `DATABASE_URL` (a plain `postgresql://` URI such as
CloudNativePG's is accepted), `VALKEY_URL`, `HOLD_TTL_SECONDS`, `EMAIL_QUEUE`, `REPORT_EMAIL`, `VERSION`,
and for the worker `SMTP_HOST`, `SMTP_PORT`, `MAIL_FROM`, `METRICS_PORT`.

## Dependencies

`requirements*.in` list the direct dependencies; the `.txt` lock files are hash-pinned and installed with
`pip --require-hashes`. To regenerate after editing an `.in` file:

```bash
docker run --rm -v "$PWD/api":/w -w /w ghcr.io/astral-sh/uv:python3.14-trixie-slim \
  uv pip compile --universal --generate-hashes --python-version 3.14 requirements.in -o requirements.txt
```
