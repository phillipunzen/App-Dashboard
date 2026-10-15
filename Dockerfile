FROM python:3.13-slim
LABEL org.opencontainers.image.title="AppDashboard" \
      org.opencontainers.image.description="AppDashboard application launcher with automatic favicons and a protected admin interface" \
      org.opencontainers.image.source="https://github.com/phillipunzen/App-Dashboard" \
      org.opencontainers.image.url="https://github.com/phillipunzen/App-Dashboard"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/dashboard.sqlite3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 appdashboard \
    && useradd --uid 10001 --gid appdashboard --no-create-home appdashboard \
    && mkdir /data && chown appdashboard:appdashboard /data
COPY --chown=appdashboard:appdashboard app ./app
USER appdashboard
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "45", "--worker-tmp-dir", "/tmp", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
