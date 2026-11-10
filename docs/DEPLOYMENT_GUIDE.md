# Plagiarism Pre-Check - Production Deployment Runbook

This guide covers deployment procedures for running Plagiarism Pre-Check in production environments, from containerized multi-node deployments to standalone Linux setups.

---

## 1. System Requirements

### Hardware Sizing

| Workload Tier | Concurrent Users | Daily Scans | Minimum CPU | Minimum RAM | Storage |
|---|---|---|---|---|---|
| **Starter / PoC** | 10–25 | Up to 500 | 2 vCPUs | 4 GB | 20 GB SSD |
| **Commercial Scale** | 50–200 | Up to 5,000 | 4–8 vCPUs | 16 GB | 100 GB NVMe |
| **High Enterprise** | 500+ | 25,000+ | 16+ vCPUs | 32 GB | 250 GB NVMe |

> [!NOTE]
> The Sentence-Transformers bi-encoder model (`all-MiniLM-L6-v2`) requires approximately 400 MB RAM per worker process. GPU acceleration (CUDA) is optional and automatically utilized if PyTorch with CUDA is installed.

---

## 2. Quickstart with Docker Compose

The simplest production-ready setup uses the bundled `docker-compose.yml`, which spins up 6 isolated, health-checked containers:
1. `api`: FastAPI web interface & REST endpoints
2. `worker-fast`: High-priority worker for text pastes & small documents
3. `worker-ocr`: Dedicated worker for multi-page PDFs and deep neural paraphrasing
4. `retention-cleaner`: Recurring cron container executing data minimization sweeps
5. `postgres`: PostgreSQL 16 relational database
6. `redis`: Redis 7 cache and job queue backend

### Step-by-Step Launch

```bash
# 1. Clone repository
git clone https://github.com/organization/plagiarism-checker.git
cd plagiarism-checker

# 2. Configure production environment
cp .env.example .env
nano .env   # Update SECRET_KEY, DB credentials, Sentry DSN, and Admin password

# 3. Build images and start containers
docker compose up -d --build

# 4. Verify running health checks
docker compose ps
curl http://localhost:8000/health
```

---

## 3. Configuration Reference (`.env`)

All platform settings are managed through environment variables or a `.env` file via Pydantic:

| Variable | Default Value | Description |
|---|---|---|
| `ENVIRONMENT` | `production` | Environment mode (`development` or `production`) |
| `DEBUG` | `false` | Enable verbose debug logs (NEVER enable in production) |
| `SECRET_KEY` | *(Must be generated)* | Cryptographic salt for JWT tokens and IP anonymization hashes |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| `1440` | JWT expiration (24 hours) |
| `DATABASE_URL` | `sqlite:///./plagiarism_dev.db` | PostgreSQL connection string (`postgresql+psycopg2://user:pass@host:5432/dbname`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string for distributed job queue |
| `SENTRY_DSN` | *(Empty)* | Sentry APM DSN for production telemetry with PII scrubber |
| `MAX_FILE_MB` | `25` | Maximum upload size in megabytes |
| `MAX_WORDS` | `50000` | Maximum word count for document uploads |
| `MAX_PASTE_WORDS` | `5000` | Maximum word count for pasted text |
| `MIN_WORDS` | `50` | Minimum word count to trigger plagiarism analysis |
| `DAILY_CHECKS_PER_USER` | `5` | Free-tier daily scan quota |
| `RAW_TEXT_RETENTION_HOURS` | `1` | Automated 1-hour purge window for data minimization |
| `METADATA_RETENTION_DAYS` | `30` | Complete metadata retention window |

---

## 4. Standalone Linux Production Deployment (Systemd + Nginx)

For bare-metal Ubuntu / Debian instances:

### 1. Python Environment Setup
```bash
sudo apt update && sudo apt install -y python3-pip python3-venv tesseract-ocr nginx
python3 -m venv /opt/plagiarism-checker/venv
source /opt/plagiarism-checker/venv/bin/activate
pip install -r requirements.txt
```

### 2. Systemd Service Definition (`/etc/systemd/system/plag-api.service`)
```ini
[Unit]
Description=Plagiarism Pre-Check FastAPI Application
After=network.target postgresql.service redis.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/plagiarism-checker
EnvironmentFile=/opt/plagiarism-checker/.env
ExecStart=/opt/plagiarism-checker/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. Systemd Retention Cleaner (`/etc/systemd/system/plag-retention.service`)
```ini
[Unit]
Description=Plagiarism Pre-Check Data Minimization Retention Sweep

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/opt/plagiarism-checker
EnvironmentFile=/opt/plagiarism-checker/.env
ExecStart=/opt/plagiarism-checker/venv/bin/python worker/retention.py
```

Create a systemd timer (`/etc/systemd/system/plag-retention.timer`) to trigger hourly:
```ini
[Unit]
Description=Run Plagiarism Data Retention Cleaner Hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Enable services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now plag-api.service plag-retention.timer
```

### 4. Nginx Reverse Proxy with TLS (SSL)
```nginx
server {
    server_name precheck.yourdomain.com;

    client_max_body_size 30M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl http2;
    ssl_certificate /etc/letsencrypt/live/precheck.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/precheck.yourdomain.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
```

---

## 5. Managed Cloud Service Integrations

- **PostgreSQL**: Fully compatible with AWS Aurora RDS, Supabase, Google Cloud SQL, and Azure Database for PostgreSQL.
  - Set `DATABASE_URL=postgresql+psycopg2://user:password@aws-rds-endpoint:5432/plagiarism`
- **Redis**: Fully compatible with Upstash Serverless Redis, AWS ElastiCache, and Redis Cloud.
  - Set `REDIS_URL=rediss://default:token@upstash-endpoint:6379`
- **Sentry APM**: Automatic zero-PII telemetry integration.
  - Set `SENTRY_DSN=https://public@sentry.io/project-id`

---

## 6. Health Checks & Diagnostics

The platform provides a live health check endpoint:
```bash
curl http://localhost:8000/health
```

Example JSON response:
```json
{
  "status": "healthy",
  "engine_version": "1.0.0",
  "database": "connected",
  "worker_disk_access": "read_write",
  "retention_status": "active",
  "timestamp": "2026-10-26T15:05:00Z"
}
```

If the database or storage fails, the endpoint returns HTTP 503 with `"status": "degraded"`.
