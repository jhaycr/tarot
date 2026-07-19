FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/ /app/backend/
RUN pip install --no-cache-dir /app/backend
COPY decks/ /app/decks/
COPY --from=frontend /build/build /app/frontend-build

ENV TAROT_STATIC_DIR=/app/frontend-build \
    TAROT_BUILTIN_DECKS=/app/decks \
    TAROT_DATA_DIR=/data

EXPOSE 8000
VOLUME /data
CMD ["uvicorn", "tarot.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
