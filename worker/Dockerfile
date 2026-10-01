# syntax=docker/dockerfile:1
FROM python:3.14.7-slim-trixie AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN python -m venv --without-pip /venv \
 && pip --python /venv/bin/python install --require-hashes -r requirements.txt

FROM python:3.14.7-slim-trixie
# Apply Debian security fixes released since the upstream base image was built.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/venv/bin:$PATH
# no pip in the runtime image
RUN python -m pip uninstall --yes --quiet pip \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=deps /venv /venv
WORKDIR /app
COPY worker.py bots.py ./
USER 10001
EXPOSE 8081
CMD ["python", "worker.py"]
