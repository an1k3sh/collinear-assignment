FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
RUN rm /etc/apt/sources.list.d/debian.sources \
    && echo 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20251101T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends \
       clang-16=1:16.0.6-15~deb12u1 libclang-rt-16-dev=1:16.0.6-15~deb12u1 \
       cmake=3.25.1-1 ninja-build=1.11.1-2~deb12u1 \
       nlohmann-json3-dev=3.11.2-2 libsqlite3-dev=3.40.1-2+deb12u2 \
    && apt-get clean
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY app/ /app/
