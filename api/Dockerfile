# syntax=docker/dockerfile:1
FROM python:3.14.7-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/venv/bin:$PATH
WORKDIR /app

FROM base AS deps
COPY requirements.txt .
# venv without pip: the runtime image ships no package installer (and none of pip's vendored CVEs)
RUN python -m venv --without-pip /venv \
 && pip --python /venv/bin/python install --require-hashes -r requirements.txt

# `docker build --target test` runs the suite against real Postgres/Valkey (see compose.yaml).
FROM deps AS test
COPY requirements-dev.txt .
RUN pip --python /venv/bin/python install --require-hashes -r requirements-dev.txt
COPY . .
CMD ["pytest", "-q"]

FROM base AS runtime
RUN python -m pip uninstall --yes --quiet pip \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=deps /venv /venv
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
# numeric UID so Pod Security "restricted" can verify runAsNonRoot
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
