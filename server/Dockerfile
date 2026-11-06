FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY server.py /app/server.py
COPY web/ /app/web/
WORKDIR /app

ENV CAPTURE_DIR=/data/captures CACHE_DIR=/cache CAPTURE_PORT=8085 BROWSE_PORT=8086
EXPOSE 8085 8086

HEALTHCHECK --interval=30s --timeout=3s \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8086/health',timeout=2)" || exit 1

CMD ["python3", "-u", "server.py"]
