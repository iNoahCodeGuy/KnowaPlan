# Deploy image for the live-dogfood test (Railway). Python pinned
# to the project's 3.12 (CLAUDE.md) — closes the 3.11 skew noted
# during the demo-slice work.
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# --proxy-headers + --forwarded-allow-ips are LOAD-BEARING, not
# cosmetic: behind Railway's proxy they make request.base_url
# honor X-Forwarded-Proto/Host, so the share links the roster
# prints read https://<public-domain>/e/... instead of an
# internal http:// hostname. Without them, every link the
# planner texts is wrong.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} \
    --proxy-headers --forwarded-allow-ips '*'
