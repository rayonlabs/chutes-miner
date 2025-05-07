# Base layer.
FROM python:3.12 as base
RUN apt update && apt -y install net-tools procps vim jq bc curl
RUN useradd chutes -s /bin/bash -d /home/chutes && mkdir -p /home/chutes && chown chutes:chutes /home/chutes
RUN mkdir -p /app && chown chutes:chutes /app
USER chutes
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH=$PATH:/home/chutes/.local/bin

# Miner/API
FROM base AS api
USER root
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && mv kubectl /usr/local/bin/ && chmod 755 /usr/local/bin/kubectl
RUN curl -fsSL -o /usr/local/bin/dbmate https://github.com/amacneil/dbmate/releases/latest/download/dbmate-linux-amd64 && chmod +x /usr/local/bin/dbmate
USER chutes
ADD --chown=chutes README.md /app/README.md
ADD --chown=chutes pyproject.toml poetry.lock /app/
WORKDIR /app
RUN poetry install --no-root
ADD --chown=chutes api /app/api
ADD --chown=chutes audit_exporter.py /app/audit_exporter.py
ADD --chown=chutes gepetto.py /app/gepetto.py
ENV PYTHONPATH=/app
ENTRYPOINT ["poetry", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM api AS sql
USER root
RUN apt-get update
RUN apt-get install -y postgresql-client
USER chutes
WORKDIR /app
ADD --chown=chutes scripts /app/scripts
RUN chmod +x /app/scripts/*.sh
RUN poetry add psycopg2-binary
ENTRYPOINT ["/app/scripts/seed.sh"]

# Cache cleaner.
FROM python:3.10-slim AS cacheclean
RUN pip install --no-cache-dir transformers==4.46.3

# GraVal bootstrap.
FROM nvidia/cuda:12.2.2-devel-ubuntu22.04 AS bootstrap
RUN apt-get -y update
RUN apt-get -y install build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev wget libbz2-dev libexpat1-dev lzma liblzma-dev libpq-dev curl
WORKDIR /usr/src
RUN wget https://www.python.org/ftp/python/3.12.7/Python-3.12.7.tgz
RUN tar -xzf Python-3.12.7.tgz
WORKDIR /usr/src/Python-3.12.7
RUN ./configure --enable-optimizations --enable-shared --with-system-expat --with-ensurepip=install --prefix=/opt/python
RUN make -j
RUN make altinstall
RUN ln -s /opt/python/bin/pip3.12 /opt/python/bin/pip
RUN ln -s /opt/python/bin/python3.12 /opt/python/bin/python
RUN echo /opt/python/lib >> /etc/ld.so.conf && ldconfig
RUN rm -rf /usr/src/Python*
RUN useradd chutes -s /bin/bash -d /home/chutes && mkdir -p /home/chutes && chown chutes:chutes /home/chutes
RUN mkdir -p /app && chown chutes:chutes /app
USER chutes
ENV PATH=/opt/python/bin:$PATH
RUN curl -sSL https://install.python-poetry.org | python -
ENV PATH=$PATH:/home/chutes/.local/bin
ADD --chown=chutes graval_bootstrap /app
WORKDIR /app
RUN poetry install --no-root
ENTRYPOINT poetry run python bootstrap.py --validator-whitelist $VALIDATOR_WHITELIST --hotkey $MINER_HOTKEY_SS58
