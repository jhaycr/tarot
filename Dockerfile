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

# Release version, supplied by CI from the git tag (metadata-action {{version}}).
# Defaults to "dev" for local/unversioned builds.
ARG TAROT_VERSION=dev

ENV TAROT_STATIC_DIR=/app/frontend-build \
    TAROT_BUILTIN_DECKS=/app/decks \
    TAROT_DATA_DIR=/data \
    TAROT_VERSION=${TAROT_VERSION}

EXPOSE 8000
VOLUME /data
# --proxy-headers: honor X-Forwarded-Proto/Host from the reverse proxy so
# request.url reflects the browser-facing https origin — the OIDC
# redirect_uri and cookie Secure flag are derived from it. Direct LAN
# requests carry no forwarded headers and are unaffected.
CMD ["uvicorn", "tarot.api.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
