FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COPILOT_AUTO_UPDATE=false
RUN rm /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260201T000000Z bookworm main\n' > /etc/apt/sources.list && \
    apt-get -o Acquire::Check-Valid-Until=false update && \
    apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation fonts-dejavu-core curl ca-certificates git && \
    apt-get clean
RUN set -eu; arch="$(dpkg --print-architecture)"; \
    case "$arch" in arm64) node_arch=arm64 ;; amd64) node_arch=x64 ;; *) exit 1 ;; esac; \
    cd /tmp; file="node-v22.14.0-linux-$node_arch.tar.gz"; \
    curl -fsSLO "https://nodejs.org/dist/v22.14.0/$file"; \
    curl -fsSLO https://nodejs.org/dist/v22.14.0/SHASUMS256.txt; \
    grep "  $file\$" SHASUMS256.txt | sha256sum --check --strict; \
    tar -xzf "$file" --strip-components=1 -C /usr/local; rm "$file" SHASUMS256.txt; \
    npm install -g @github/copilot@1.0.102 --fetch-timeout=180000 --fetch-retries=2
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY app/ /app/
