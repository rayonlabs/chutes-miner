# Cache cleaner.
FROM python:3.10-slim AS base
RUN pip install --no-cache-dir transformers==4.46.3

FROM base AS production


FROM base AS development