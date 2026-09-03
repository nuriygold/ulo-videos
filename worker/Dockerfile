FROM python:3.12-slim

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends blender ffmpeg fonts-dejavu-core librsvg2-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app/worker

ENV PYTHONUNBUFFERED=1 \
    PORT=8080
EXPOSE 8080

CMD ["python", "-m", "worker.service"]
