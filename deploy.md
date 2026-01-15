# AI Witness Finder - Complete Deployment Guide

## Project Info
- **Railway Project:** AIWitnessOrganizer
- **Project ID:** 390a5fc9-e48a-46d1-abe1-ed5e02191b19
- **Railway URL:** https://railway.com/project/390a5fc9-e48a-46d1-abe1-ed5e02191b19
- **GitHub Repo:** https://github.com/jeebus87/AIWitnessOrganizer
- **Firebase Console:** https://console.firebase.google.com/project/aiwitness-finder

---

## Current Status

### Already Configured:
- [x] PostgreSQL database provisioned on Railway
- [x] Stripe products created (Juridion Labs account)
- [x] Firebase project created (aiwitness-finder)
- [x] GitHub repository created and pushed
- [x] Clio Developer App configured (App ID: 25010)

### Needs Manual Setup:
- [ ] Add Redis service to Railway
- [ ] Connect GitHub repo to Railway service
- [ ] Configure environment variables
- [ ] Enable Firebase Authentication
- [ ] Run database migrations

---

## Step 1: Add Redis to Railway (Dashboard)

1. Open Railway: https://railway.com/project/390a5fc9-e48a-46d1-abe1-ed5e02191b19
2. Click **"+ New"** → **"Database"** → **"Redis"**
3. Wait for Redis to provision

---

## Step 2: Add API Service from GitHub

1. In Railway dashboard, click **"+ New"** → **"GitHub Repo"**
2. Select repository: `jeebus87/AIWitnessOrganizer`
3. Railway will auto-detect Python and deploy
4. Name the service: `aiwitnessfinder-api`

---

## Step 3: Configure Environment Variables

In the API service settings, add these variables:

```bash
# Core
APP_NAME=AIWitnessFinder
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=your-secure-random-string-here

# Database (reference Railway Postgres)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Redis (reference Railway Redis)
REDIS_URL=${{Redis.REDIS_URL}}

# Clio OAuth (from Clio Developer Dashboard)
CLIO_CLIENT_ID=PKQa4hMGOIYyYHcnuwiIW75Dy4Lwj3zNwGnBfLSq
CLIO_CLIENT_SECRET=<from-clio-dashboard>
CLIO_REDIRECT_URI=https://YOUR-RAILWAY-DOMAIN/api/v1/auth/callback

# AWS Bedrock
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1:0

# Firebase
FIREBASE_PROJECT_ID=aiwitness-finder
FIREBASE_API_KEY=AIzaSyDARGN0xurmAH7pV6zle-rCE-jteStq730
FIREBASE_AUTH_DOMAIN=aiwitness-finder.firebaseapp.com
FIREBASE_STORAGE_BUCKET=aiwitness-finder.firebasestorage.app
FIREBASE_MESSAGING_SENDER_ID=270053020694
FIREBASE_APP_ID=1:270053020694:web:7711fdcea329dc31d5d137

# Stripe (Juridion Labs - Test Mode)
# Get keys from: stripe config --list
STRIPE_SECRET_KEY=<from-stripe-cli>
STRIPE_PUBLISHABLE_KEY=<from-stripe-cli>
STRIPE_PRICE_BASIC=price_1SpkLcBS2VKrUF7Ru3SNu2Wp
STRIPE_PRICE_PROFESSIONAL=price_1SpkLsBS2VKrUF7RJJty99ye
STRIPE_PRICE_ENTERPRISE=price_1SpkLuBS2VKrUF7Rz2AAxSgu

# Encryption
FERNET_KEY=I1W4_PkClWkGXlZZw3rSM5mP4qxbC0TyIG-ZCd50UmU=

# CORS (update with your frontend domain)
FRONTEND_URL=https://aiwitnessorganizer-web.up.railway.app
```

---

## Step 4: Add Celery Worker Service

1. In Railway, click **"+ New"** → **"GitHub Repo"**
2. Select same repo: `jeebus87/AIWitnessOrganizer`
3. Name the service: `aiwitnessfinder-worker`
4. Set **Start Command**: `celery -A app.worker.celery_app worker --loglevel=info`
5. Add the **same environment variables** as the API service

---

## Step 5: Enable Firebase Authentication

1. Open Firebase Console: https://console.firebase.google.com/project/aiwitness-finder/authentication
2. Click **"Get started"**
3. Enable **Email/Password** provider
4. (Optional) Enable **Google** sign-in

---

## Step 6: Run Database Migrations

After API service deploys successfully:

```bash
cd /c/Projects/AIWitnessFinder
railway link --project 390a5fc9-e48a-46d1-abe1-ed5e02191b19
railway service link aiwitnessfinder-api
railway run alembic upgrade head
```

---

## Step 7: Update Clio Redirect URIs

After getting your Railway domain:

1. Go to Clio Developer Dashboard: https://app.clio.com/settings/developer_applications/25010
2. Update Redirect URIs with actual Railway domain:
   - `https://YOUR-RAILWAY-DOMAIN/api/v1/auth/callback`

---

## Stripe Products Created

| Tier | Product ID | Price ID | Monthly Price |
|------|------------|----------|---------------|
| Basic | prod_TnL1tooBCSVUGT | price_1SpkLcBS2VKrUF7Ru3SNu2Wp | $49 |
| Professional | prod_TnL1mIKgzHL85T | price_1SpkLsBS2VKrUF7RJJty99ye | $149 |
| Enterprise | prod_TnL12NlmHtqvd5 | price_1SpkLuBS2VKrUF7Rz2AAxSgu | $499 |

---

## Quick Commands

```bash
# Link to project
railway link --project 390a5fc9-e48a-46d1-abe1-ed5e02191b19

# View all services
railway service status --all

# View logs for a service
railway logs --service aiwitnessfinder-api

# View environment variables
railway variables

# Run a command in Railway environment
railway run python -c "print('Connected!')"

# Redeploy service
railway redeploy --service aiwitnessfinder-api
```

---

## PostgreSQL Connection Details

- **Internal URL:** `postgres.railway.internal:5432`
- **External URL:** `interchange.proxy.rlwy.net:41696`
- **Database:** `railway`
- **User:** `postgres`
- **Password:** (see Railway dashboard or run `railway variables`)

---

## Verification Checklist

After deployment, verify:

1. [ ] API health check: `GET /health` returns `{"status": "healthy"}`
2. [ ] Swagger docs (if debug=true): `/docs`
3. [ ] Clio OAuth flow works: `/api/v1/auth/clio`
4. [ ] Database migrations applied: Check tables exist
5. [ ] Redis connection works: Celery tasks execute
6. [ ] Stripe webhooks configured (optional)

---

## Troubleshooting

### Database Connection Issues
- Ensure `DATABASE_URL` uses `postgresql+asyncpg://` prefix
- Check PostgreSQL service is running in Railway

### Redis Connection Issues
- Verify `REDIS_URL` is correctly set from `${{Redis.REDIS_URL}}`
- Ensure Redis service is provisioned

### Celery Worker Not Processing
- Check worker logs: `railway logs --service aiwitnessfinder-worker`
- Verify Redis connection
- Ensure worker has same env vars as API

### Clio OAuth Errors
- Verify redirect URI matches exactly (including trailing slashes)
- Check client ID and secret are correct
