FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY app/ /app/
RUN python /app/carrier_service.py initialize \
    --seed /app/carrier-incident/seed.json --database /app/carrier/state.sqlite
