# AI Witness Finder - Railway Deployment Guide

## Project Info
- **Railway Project:** AIWitnessOrganizer
- **Project ID:** 390a5fc9-e48a-46d1-abe1-ed5e02191b19
- **GitHub Repo:** https://github.com/jeebus87/AIWitnessOrganizer
- **PostgreSQL:** Already provisioned

## Step 1: Connect GitHub Repository

1. Open Railway dashboard: https://railway.com/project/390a5fc9-e48a-46d1-abe1-ed5e02191b19
2. Click "New Service" → "GitHub Repo"
3. Select `jeebus87/AIWitnessOrganizer`
4. Railway will auto-detect Python and deploy

## Step 2: Add Redis Service

1. In Railway dashboard, click "New Service" → "Database" → "Redis"
2. This creates the Redis instance for Celery

## Step 3: Configure Environment Variables

Add these variables to the API service:

```bash
# Core Config
APP_NAME=AIWitnessFinder
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<generate-secure-key>

# Database (auto-configured from Postgres service)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Redis (auto-configured from Redis service)
REDIS_URL=${{Redis.REDIS_URL}}

# Clio OAuth
CLIO_CLIENT_ID=PKQa4hMGOIYyYHcnuwiIW75Dy4Lwj3zNwGnBfLSq
CLIO_CLIENT_SECRET=YlKoOGlNxczG0xPhnTk6Qx5SwJvDNDpKUIWotiFp
CLIO_REDIRECT_URI=https://aiwitnessorganizer-production.up.railway.app/api/v1/auth/callback

# AWS Bedrock (add your credentials)
AWS_ACCESS_KEY_ID=<your-aws-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret>
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1:0

# Encryption Key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
FERNET_KEY=<generate-key>

# CORS
FRONTEND_URL=https://aiwitnessorganizer-web.up.railway.app
```

## Step 4: Add Celery Worker Service

1. In Railway, create a new service from the same GitHub repo
2. Name it `worker`
3. Set the start command: `celery -A app.worker.celery_app worker --loglevel=info`
4. Add the same environment variables as the API service

## Step 5: Run Database Migrations

After the API service deploys, run:

```bash
railway run alembic upgrade head
```

## Step 6: Configure Domain

1. Go to the API service settings
2. Under "Networking" → "Public Domain"
3. Either use Railway's generated domain or add a custom domain

## Redirect URIs to Update in Clio

After deployment, update Clio Developer App with the actual Railway domain:
1. Go to https://app.clio.com/settings/developer_applications/25010
2. Update Redirect URIs with the Railway domain

## Quick Commands

```bash
# View logs
railway logs

# Check status
railway status

# Run a command in Railway environment
railway run python -c "print('Hello from Railway')"

# View environment variables
railway variables
```

## Database Connection (for local development)

PostgreSQL is available at:
- **Internal:** `postgres.railway.internal:5432`
- **External:** `interchange.proxy.rlwy.net:41696`
- **Database:** `railway`
- **User:** `postgres`
- **Password:** Check Railway dashboard or run `railway variables`
