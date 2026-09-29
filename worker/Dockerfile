# syntax=docker/dockerfile:1
FROM python:3.14.7-slim-trixie AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install --require-hashes -r requirements.txt

FROM python:3.14.7-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/venv/bin:$PATH
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=deps /venv /venv
WORKDIR /app
COPY worker.py .
USER 10001
EXPOSE 8081
CMD ["python", "worker.py"]
