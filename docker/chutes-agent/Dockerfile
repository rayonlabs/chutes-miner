# Base layer.
FROM python:3.12 AS base

ARG PROJECT_DIR
ARG PROJECT

# Remove additional packages for TEE?
RUN apt update && apt -y install net-tools procps vim jq bc curl

RUN useradd chutes -s /bin/bash -d /home/chutes && mkdir -p /home/chutes && chown chutes:chutes /home/chutes
RUN mkdir -p /app && chown chutes:chutes /app

FROM base AS build

ARG PROJECT_DIR
ARG PROJECT

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

RUN python -m venv .venv
COPY --chown=chutes:chutes /src/chutes-common /app/chutes-common
COPY --chown=chutes:chutes ${PROJECT_DIR}/pyproject.toml ${PROJECT_DIR}/poetry.lock ${PROJECT_DIR}/README.md  ./${PROJECT}/
RUN . .venv/bin/activate && poetry install --only main --no-root -P ${PROJECT}
COPY --chown=chutes:chutes ${PROJECT_DIR}/ ./${PROJECT}/
RUN . .venv/bin/activate && poetry install --only main -P ${PROJECT}

# Miner/API
FROM base AS production

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

USER ${APP_USER}
WORKDIR /app

COPY --from=build /app /app

ENTRYPOINT ["python", "-m", "uvicorn", "--host", "0.0.0.0", "--port", "8000", "chutes_agent.api.main:app"]

FROM build AS development

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

USER root

WORKDIR /app
COPY --chown=chutes:chutes ${PROJECT_DIR}/ ./${PROJECT}/
RUN . .venv/bin/activate && poetry install -P ${PROJECT}
COPY --chown=chutes:chutes tests/${PROJECT}/ ./tests/${PROJECT}
COPY --chown=chutes:chutes tests/fixtures/ ./tests/fixtures/
COPY --chown=chutes:chutes tests/*.py ./tests
RUN chown ${APP_USER}:${APP_GROUP} .

