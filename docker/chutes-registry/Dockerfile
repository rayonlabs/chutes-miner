# Base layer.
FROM python:3.12 AS base

ARG PROJECT_DIR
ARG PROJECT

RUN apt update && apt -y install net-tools procps vim jq bc curl
RUN useradd chutes -s /bin/bash -d /home/chutes && mkdir -p /home/chutes && \
    chown chutes:chutes /home/chutes
RUN mkdir -p /app && \
    chown chutes:chutes /app

USER chutes

ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  POETRY_VERSION=2.1.2 \
  POETRY_VIRTUALENVS_IN_PROJECT=true \
  POETRY_NO_INTERACTION=1

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH=$PATH:/home/chutes/.local/bin

WORKDIR /app

COPY --chown=chutes:chutes /src/chutes-common /app/chutes-common
COPY --chown=chutes:chutes ${PROJECT_DIR}/ ./${PROJECT}/
RUN python -m venv .venv
RUN . .venv/bin/activate && poetry install --only main -P /app/${PROJECT}

FROM base AS production

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

USER ${APP_USER}
WORKDIR /app

COPY --from=base /app .

ENTRYPOINT ["python", "-m", "uvicorn", "--host", "0.0.0.0", "--port", "8000", "--reload", "chutes_registry.main:app"]

FROM base AS development

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

USER root

WORKDIR /app
RUN . .venv/bin/activate && poetry install -P /app/${PROJECT}
RUN chown ${APP_USER}:${APP_GROUP} .