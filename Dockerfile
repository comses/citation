# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt1-dev \
    libpq-dev \
    postgresql-client \
    curl \
    git \
    wget

COPY requirements-dev.txt requirements.txt /tmp/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r /tmp/requirements-dev.txt

WORKDIR /code
COPY --link . /code

CMD ["invoke", "coverage"]
