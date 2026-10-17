FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/prozesspilot
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 prozesspilot && mkdir /data && chown 10001:10001 /data
COPY app/ ./app/
COPY scripts/ ./scripts/
USER 10001
EXPOSE 8080
ENV DATABASE_PATH=/data/prozesspilot.sqlite3 APP_ENV=local
CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
