FROM --platform=linux/amd64 python:3.12-slim

ARG TARGETARCH
ARG BLENDER_VERSION=5.2.1
ARG BLENDER_SHA256=a31f524fa99a527d3d52b7f5aaa68c34e1a19d5a1c9473f79c5cc610fd5b10e9

RUN test "${TARGETARCH}" = "amd64" || (echo "ulo-videos render worker requires linux/amd64" >&2; exit 1)

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg fonts-dejavu-core librsvg2-bin xz-utils \
        libasound2 libegl1 libgl1 libglx0 libx11-6 libxi6 libxrender1 libxxf86vm1 \
        libxfixes3 libxkbcommon0 libsm6 libice6 libfontconfig1 libdbus-1-3 libwayland-client0 \
    && curl -fsSL "https://download.blender.org/release/Blender5.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz" -o /tmp/blender.tar.xz \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum -c - \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz --strip-components=1 -C /opt/blender \
    && ln -s /opt/blender/blender /usr/local/bin/blender \
    && rm -f /tmp/blender.tar.xz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY worker /app/worker

ENV PYTHONUNBUFFERED=1 \
    PORT=8080
EXPOSE 8080

CMD ["python", "-m", "worker.service"]
