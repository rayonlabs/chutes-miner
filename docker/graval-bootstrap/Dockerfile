FROM parachutes/python:3.12.9 AS base-cuda

ARG PROJECT_DIR
ARG PROJECT

USER chutes

ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  POETRY_VERSION=2.1.2 \
  POETRY_VIRTUALENVS_IN_PROJECT=true \
  POETRY_NO_INTERACTION=1

RUN curl -sSL https://install.python-poetry.org | python -
ENV PATH=$PATH:/home/chutes/.local/bin
COPY --chown=chutes:chutes ${PROJECT_DIR}/ ./${PROJECT}/
RUN python -m venv .venv
RUN . .venv/bin/activate && poetry install --only main -P /app/${PROJECT}

FROM parachutes/python:3.12.3-rocm AS base-rocm

ARG PROJECT_DIR
ARG PROJECT

USER chutes

ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  POETRY_VERSION=2.1.2 \
  POETRY_VIRTUALENVS_IN_PROJECT=true \
  POETRY_NO_INTERACTION=1

RUN curl -sSL https://install.python-poetry.org | python -
ENV PATH=$PATH:/home/chutes/.local/bin
COPY --chown=chutes:chutes ${PROJECT_DIR}/ ./${PROJECT}/
RUN python -m venv .venv
RUN . .venv/bin/activate && poetry install --only main -P /app/${PROJECT}

FROM parachutes/python:3.12.9 AS production-cuda

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes
ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1

USER ${APP_USER}
WORKDIR /app

COPY --from=base /app .

ENTRYPOINT ["python", "bootstrap.py"]

FROM parachutes/python:3.12.3-rocm AS production-rocm

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1

USER ${APP_USER}
WORKDIR /app

COPY --from=base /app .

ENTRYPOINT ["python", "bootstrap.py"]

FROM base-cuda AS development-cuda

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

WORKDIR /app
RUN . .venv/bin/activate && poetry install -P /app/${PROJECT}
RUN chown ${APP_USER}:${APP_GROUP} .

FROM base-rocm AS development-rocm

ARG PROJECT_DIR
ARG PROJECT

ENV PATH="/app/.venv/bin:$PATH"
ENV APP_USER=chutes
ENV APP_GROUP=chutes

WORKDIR /app
RUN . .venv/bin/activate && poetry install -P /app/${PROJECT}
RUN chown ${APP_USER}:${APP_GROUP} .