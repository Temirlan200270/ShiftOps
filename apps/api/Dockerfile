# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
# Production image: do not install dev tools (ruff, pytest) — less RAM and smaller layers.
RUN pip install --upgrade pip \
    && pip install -e "."

COPY . .
# Edits on Windows can leave CRLF in .conf; supervisord treats \r as part of the line and breaks (uvicorn never binds).
# Supervisor config baked in. We do NOT use it as the default CMD because
# `docker-compose.yml` still wants `api` and `worker` as separate services
# (cleaner for local development logs and hot-reload). Fly.io overrides the
# command via `fly.toml` to launch supervisord, which co-locates uvicorn +
# taskiq worker on a single small machine — that's how we fit a free-tier
# budget without losing the worker.
COPY deploy/supervisord.conf /etc/supervisor/conf.d/shiftops.conf
RUN sed -i 's/\r$//' /etc/supervisor/conf.d/shiftops.conf

EXPOSE 8000

CMD ["uvicorn", "shiftops_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
