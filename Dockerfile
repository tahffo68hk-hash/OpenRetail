FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/openretail
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd -g 10001 retail && useradd -u 10001 -g 10001 -r -M retail \
    && mkdir -p /srv/openretail/data /srv/openretail/backups \
    && chown -R retail:retail /srv/openretail
COPY --chown=retail:retail openretail ./openretail
COPY --chown=retail:retail web ./web
COPY --chown=retail:retail scripts ./scripts
USER retail
EXPOSE 8000
CMD ["uvicorn", "openretail.main:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
