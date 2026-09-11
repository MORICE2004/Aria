# ARIA Production Deployment Runbook

This guide contains the end-to-end production deployment instructions for **ARIA** using:
- **Vercel**: Next.js 16 Dashboard and public edge layer.
- **DigitalOcean**: Persistent FastAPI backend, PostgreSQL 16 (pgvector), Redis, background workers, and Baileys WhatsApp bridge.

---

## 1. Architecture Overview

```
                          [ Internet / Browser / Mobile Phone ]
                                           │
                   ┌───────────────────────┴───────────────────────┐
                   ▼                                               ▼
         [ Vercel Edge Layer ]                          [ DigitalOcean API Host ]
    https://aria.yourdomain.com                     https://api.yourdomain.com
    ┌───────────────────────────┐                   ┌───────────────────────────────┐
    │  Next.js 16 Dashboard     │                   │  FastAPI Core (Port 8000)     │
    │  - Global Edge CDN        │ ──(REST/JWT)────► │  - Action Gateway & Security   │
    │  - /api/health (Edge)     │                   │  - Inbound Queue Drain Worker │
    │  - React 19 UI Components │                   │  - Proactive Diagnostic Engine│
    └───────────────────────────┘                   │  - Headless Playwright Worker │
                                                    └──────────────┬────────────────┘
                                                                   │
                                  ┌────────────────────────────────┼────────────────────────────────┐
                                  ▼                                ▼                                ▼
                    ┌──────────────────────────┐     ┌───────────────────────────┐    ┌──────────────────────────┐
                    │ PostgreSQL 16 + pgvector │     │    Redis 7 (In-Memory)    │    │ WhatsApp Bridge (Baileys)│
                    │ - Conversations          │     │ - Fast Cache & Locks      │    │                          │
                    │ - Semantic Memory & RAG  │     │ - Ephemeral Rate Limits   │    │ [Observer (index.js)]    │
                    │ - Action Audit Ledger    │     └───────────────────────────┘    │  ├─ Persistent Socket    │
                    │ - Style & Relationships  │                                      │  └─ Volume: aria_wa_auth │
                    └──────────────────────────┘                                      │                          │
                                                                                      │ [Sender (sender.js)]     │
                                                                                      │  ├─ Outbound Queue Poll  │
                                                                                      │  ├─ Typing Delay (2.4s)  │
                                                                                      │  └─ Volume: aria_sender  │
                                                                                      └──────────────────────────┘
```

---

## 2. Prerequisites & Cloud Accounts

1. **Vercel Account**: For deploying the Next.js frontend (`apps/web`). Free tier or Pro.
2. **DigitalOcean Account**:
   - Option A (Recommended): **1x Droplet (Ubuntu 24.04 x64, 2GB RAM / 1 vCPU - \$12/mo)** using Docker Compose.
   - Option B: **DigitalOcean App Platform** with Managed PostgreSQL and Redis.
3. **Domain Name**: E.g. `yourdomain.com` with access to DNS records (Cloudflare, Namecheap, Route53).
4. **Google AI Studio API Key**: For `gemini-3.6-flash`.
5. **WhatsApp Account**: A phone with WhatsApp installed to pair via multi-device QR code.

---

## 3. Environment Variables Reference

### Vercel Environment Variables (Frontend)
| Variable | Description | Example |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_API_URL` | Public HTTPS URL of the DigitalOcean API | `https://api.yourdomain.com` |

### DigitalOcean Environment Variables (Backend & Workers)
| Variable | Description | Example |
| :--- | :--- | :--- |
| `APP_ENV` | Environment identifier | `production` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `DATABASE_URL` | PostgreSQL connection string with asyncpg | `postgresql+asyncpg://aria:<password>@postgres:5432/aria` |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins | `https://aria.yourdomain.com,https://aria-web.vercel.app` |
| `ARIA_PASSWORD` | Master password for dashboard login | Strong passphrase |
| `SECRET_KEY` | 32+ char hex secret for signing JWTs | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `LLM_PROVIDER` | Primary AI provider | `gemini` |
| `GEMINI_API_KEY` | Google Gemini API key | `AQ.Ab8...` |
| `GEMINI_MODEL` | Google Gemini model name | `gemini-3.6-flash` |
| `OPENCLAW_INGEST_SECRET` | Secret token between WhatsApp bridge and API | `python -c "import secrets; print('aria_ingest_' + secrets.token_hex(24))"` |
| `WHATSAPP_WORKER_ENABLED` | Enables inbound retry and queue drain worker | `true` |
| `PROACTIVE_ENABLED` | Enables 5-minute autonomous diagnostic checks | `true` |
| `TAVILY_API_KEY` | Optional Tavily search API key | `tvly-...` |
| `SENTRY_DSN` | Optional Sentry DSN for error telemetry | `https://...@sentry.io/...` |

---

## 4. DigitalOcean Deployment (Step-by-Step)

### Option A: DigitalOcean Droplet with Docker Compose (Recommended)

1. **Create Droplet**:
   - Image: Ubuntu 24.04 LTS.
   - Size: Basic, Regular SSD (\$12/month, 2GB RAM, 1 CPU).
   - Region: Closest to your physical location (e.g. Frankfurt, London, NYC).
   - Authentication: SSH Key.

2. **Server Initial Setup**:
   Connect via SSH:
   ```bash
   ssh root@<DROPLET_IP>
   ```
   Install Docker and Docker Compose:
   ```bash
   apt-get update && apt-get install -y git curl ufw
   curl -fsSL https://get.docker.com | sh
   systemctl enable docker
   systemctl start docker
   ```

3. **Configure Firewall**:
   ```bash
   ufw allow OpenSSH
   ufw allow 80/tcp
   ufw allow 443/tcp
   ufw enable
   ```

4. **Clone Repository & Configure Environment**:
   ```bash
   git clone https://github.com/<your-username>/Aria.git /opt/aria
   cd /opt/aria
   cp .env.example .env
   nano .env
   ```
   *Fill in your real secrets (`ARIA_PASSWORD`, `SECRET_KEY`, `OPENCLAW_INGEST_SECRET`, `GEMINI_API_KEY`).*

5. **Start Persistent Stack**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
   Verify all 5 services are running:
   ```bash
   docker compose -f docker-compose.prod.yml ps
   ```

6. **Set up Nginx Reverse Proxy & Free Let's Encrypt SSL**:
   Install Certbot and Nginx:
   ```bash
   apt-get install -y nginx certbot python3-certbot-nginx
   ```
   Create `/etc/nginx/sites-available/aria-api`:
   ```nginx
   server {
       server_name api.yourdomain.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 300s;
           proxy_connect_timeout 60s;
       }
   }
   ```
   Enable site and obtain SSL:
   ```bash
   ln -s /etc/nginx/sites-available/aria-api /etc/nginx/sites-enabled/
   nginx -t
   systemctl reload nginx
   certbot --nginx -d api.yourdomain.com --non-interactive --agree-tos -m your-email@example.com
   ```

---

## 5. WhatsApp Multi-Device Pairing & Session Persistence

The WhatsApp bridge runs as two separate containers:
1. `aria-wa-observer` (listens for incoming messages)
2. `aria-wa-sender` (sends approved outgoing replies)

Both store their session encryption keys on persistent Docker volumes (`aria_wa_auth` and `aria_wa_sender`).

### Pairing on Remote Server
Check the container logs to view the terminal QR code:
```bash
# 1. Pair the observer device
docker compose -f docker-compose.prod.yml logs -f whatsapp-observer
```
*Open WhatsApp on your phone $\rightarrow$ Linked Devices $\rightarrow$ Link a Device $\rightarrow$ Scan the QR code in terminal.*

```bash
# 2. Pair the sender device
docker compose -f docker-compose.prod.yml logs -f whatsapp-sender
```
*Scan the second QR code. Once paired, credentials survive reboots and container upgrades.*

### Migrating Existing Sessions from Local Machine (Optional)
If you already paired ARIA locally, you can rsync your local credentials directly into the server volumes:
```bash
# Copy local auth states to remote host
scp -r apps/wa-bridge/auth root@<DROPLET_IP>:/tmp/wa-auth
scp -r apps/wa-bridge/auth-sender root@<DROPLET_IP>:/tmp/wa-auth-sender

# Copy inside the Docker volumes
docker cp /tmp/wa-auth/. aria-wa-observer:/app/auth/
docker cp /tmp/wa-auth-sender/. aria-wa-sender:/app/auth-sender/
```

---

## 6. Vercel Deployment (Step-by-Step)

1. **Import Repository to Vercel**:
   - Go to [vercel.com](https://vercel.com) $\rightarrow$ Add New Project $\rightarrow$ Import your GitHub repository.
2. **Project Settings**:
   - **Framework Preset**: Next.js
   - **Root Directory**: Select `apps/web` (or leave as root if using root `vercel.json`).
   - **Build Command**: `npm run build`
   - **Output Directory**: `.next`
3. **Configure Environment Variables in Vercel**:
   - `NEXT_PUBLIC_API_URL`: Set to `https://api.yourdomain.com`
4. **Deploy**:
   - Click **Deploy**. Vercel will build the 19 routes and deploy globally to Edge CDN in ~45 seconds.
5. **Custom Domain**:
   - Go to Project Settings $\rightarrow$ Domains $\rightarrow$ Add `aria.yourdomain.com`.
   - Add the CNAME record in your DNS provider pointing to `cname.vercel-dns.com`.

---

## 7. Database Migrations & Integrity Verification

Database migrations are automated! When the `api` container boots, `src/db.py` executes:
1. `CREATE EXTENSION IF NOT EXISTS vector` (enables pgvector)
2. `alembic upgrade head` (applies all migrations in `apps/api/migrations`)

To manually verify or inspect schema revisions:
```bash
docker exec -it aria-api alembic current
```
To run automated integrity checks:
```bash
docker exec -it aria-api python -c "
import asyncio
from src.db import engine
from sqlalchemy import text

async def check():
    async with engine.connect() as conn:
        res = await conn.execute(text('SELECT 1'))
        print('DB reachable:', res.scalar() == 1)

asyncio.run(check())
"
```

---

## 8. Remote Access (Phone & Computer)

- **From Phone**: Open Safari/Chrome and navigate to `https://aria.yourdomain.com`. Tap "Share" $\rightarrow$ "Add to Home Screen" for an app-like PWA experience.
- **Login**: Enter your `ARIA_PASSWORD`. A 7-day secure JWT token will be saved to your browser.
- **Bi-directional Notifications**: The dashboard polls `/health`, `/ready`, `/whatsapp/overview`, and `/notifications` with zero WebSocket battery drain.

---

## 9. Verification Checklist

Execute these checks after deployment:

- [ ] **Vercel Edge Health**: `curl -I https://aria.yourdomain.com/api/health` $\rightarrow$ `HTTP/2 200`
- [ ] **DigitalOcean API Liveness**: `curl https://api.yourdomain.com/health` $\rightarrow `{"status":"ok","env":"production","version":"0.3.0"}`
- [ ] **System Readiness Check**: `curl https://api.yourdomain.com/ready` $\rightarrow `{"ready":true,"checks":{...}}`
- [ ] **CORS Verification**: Preflight request from Vercel domain:
  ```bash
  curl -H "Origin: https://aria.yourdomain.com" \
       -H "Access-Control-Request-Method: POST" \
       -H "Access-Control-Request-Headers: Content-Type,Authorization" \
       -X OPTIONS https://api.yourdomain.com/auth/login -i
  ```
- [ ] **WhatsApp Observer Online**: `docker logs --tail 20 aria-wa-observer` $\rightarrow `[observer] socket connected`
- [ ] **WhatsApp Sender Online**: `docker logs --tail 20 aria-wa-sender` $\rightarrow `[sender] socket connected`

---

## 10. Rollback Procedure

If a bad commit is pushed:

1. **Vercel Frontend Rollback**:
   - Go to Vercel Dashboard $\rightarrow$ Deployments.
   - Click the three dots on the previous working deployment $\rightarrow$ **Instant Rollback**.
2. **DigitalOcean Backend Rollback**:
   ```bash
   cd /opt/aria
   git checkout <PREVIOUS_COMMIT_SHA>
   docker compose -f docker-compose.prod.yml up -d --build
   ```
   If a database migration needs to be downgraded:
   ```bash
   docker exec -it aria-api alembic downgrade -1
   ```

---

## 11. Troubleshooting Guide

| Issue | Root Cause | Resolution |
| :--- | :--- | :--- |
| **CORS Error in Browser** | `CORS_ORIGINS` missing frontend domain | Add `https://aria.yourdomain.com` to `CORS_ORIGINS` in `/opt/aria/.env` and run `docker compose up -d`. |
| **WhatsApp Disconnected** | Phone lost connection or QR expired | Check logs: `docker compose logs -f whatsapp-observer`. Rescan the QR code if prompted. |
| **502 Bad Gateway from Nginx** | FastAPI container stopped or restarting | Check API container logs: `docker logs --tail 50 aria-api`. Verify database health: `docker ps`. |
| **Outbound Message Not Sent** | Autonomy mode is `observe` or contact not trusted | Open WhatsApp page in dashboard, ensure contact trust is `trusted` or `high`, and mode is `limited_autonomy`. |
| **Playwright Browser Failure** | Missing Linux dependencies | Ensure using `Dockerfile.api` which installs Debian packages for Chromium. |
