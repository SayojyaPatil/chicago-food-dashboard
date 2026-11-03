# One image for both the web service and the ETL job.
# Stage 1: build the React app.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same-origin API: the FastAPI service serves these files.
ENV VITE_API_URL=""
RUN npm run build

# Stage 2: Python runtime.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY etl/ ./etl/
COPY scripts/ ./scripts/
COPY evals/ ./evals/
COPY --from=web /web/dist ./static
RUN useradd --uid 10001 --no-create-home appuser
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
