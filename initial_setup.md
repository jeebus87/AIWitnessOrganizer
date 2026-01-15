# AI Witness Finder - Development Plan

## Project Overview

Automated Legal Witness Extraction System that integrates with Clio API and AWS Bedrock Claude 4.5 Sonnet to extract witness information from legal discovery documents.

### Key Features
- OAuth 2.0 integration with Clio Manage
- Document processing (PDFs, images, Outlook .msg/.eml files with recursive extraction)
- AI-powered witness extraction using Claude 4.5 Sonnet vision capabilities
- Structured output in PDF and Excel formats
- Rate-limited API access with async job processing
- Zero-retention security model

---

## Architecture Decisions (Brainstormed with Gemini CLI)

### Authentication
- **Firebase Auth** for user identity management (scalable, secure, client SDKs)
- **Clio OAuth tokens** stored encrypted in PostgreSQL (linked to Firebase UID)
- Separation of app users from Clio credentials

### Data Persistence
- **PostgreSQL** for relational data (users, matters, documents, witnesses, jobs)
- Enforces data integrity with foreign keys
- Better for complex queries across related entities

### Async Processing
- **Celery + Redis** for reliable background job processing
- Workers scale independently from web server
- Automatic retries with exponential backoff

### Document Processing
- **extract-msg** for Outlook .msg files (pure Python, cross-platform)
- **pdf2image** (poppler) for PDF to image conversion
- **Pillow** for image resizing/compression

### AI Integration
- **AWS Bedrock** with Claude 4.5 Sonnet (model ID: `anthropic.claude-sonnet-4-5-20250929-v1:0`)
- Vision API for direct document analysis (more reliable than OCR)
- Structured JSON output with detailed prompts

### Deployment
- **Railway** for FastAPI web server + Celery workers
- Shared PostgreSQL and Redis connections via Railway service references

---

## Development Phases

### Phase 1: Backend Foundation - COMPLETE
- [x] Initialize project structure
- [x] Create requirements.txt with all dependencies
- [x] Set up core configuration (pydantic-settings)
- [x] Create security module (Fernet encryption, password hashing)
- [x] Define SQLAlchemy database models
- [x] Set up database migrations (Alembic)
- [x] Create main FastAPI application
- [x] Configure CORS and middleware
- [x] Initialize Git repository
- [x] Create GitHub repository

### Phase 2: Clio OAuth Integration - COMPLETE
- [x] Create Clio OAuth endpoints (/auth/clio, /auth/callback, /auth/refresh)
- [x] Implement token encryption/decryption for storage
- [x] Build Clio API client with rate limiting
- [x] Implement token auto-refresh logic
- [x] Handle 302 redirects for document downloads
- [x] Create pagination handlers for large matter/document lists

### Phase 3: Document Processing Pipeline - COMPLETE
- [x] Build file type detection service
- [x] Implement recursive MSG/EML parser (extract-msg)
- [x] Create PDF to image converter (pdf2image)
- [x] Build image preprocessing (resize, compress for Bedrock limits)
- [x] Create document ingestion Celery tasks
- [x] Implement temporary file cleanup (zero-retention)

### Phase 4: AI Witness Extraction - COMPLETE
- [x] Create AWS Bedrock client with boto3
- [x] Design witness extraction prompts (all witnesses, specific targets)
- [x] Build JSON schema validation for AI responses
- [x] Implement retry logic for throttling
- [x] Create witness extraction Celery tasks
- [x] Build result aggregation and deduplication

### Phase 5: Export Generation - COMPLETE
- [x] Create PDF export engine (ReportLab)
- [x] Build Excel export engine (pandas + XlsxWriter)
- [x] Add hyperlinks to source documents in Clio
- [x] Implement conditional formatting (importance levels)
- [x] Create export endpoints

### Phase 6: Firebase & Stripe Integration - PENDING
- [ ] Set up Firebase Admin SDK
- [ ] Create Firebase auth verification middleware
- [ ] Build user registration/login flows
- [ ] Integrate Stripe billing
- [ ] Implement subscription tier enforcement
- [ ] Create webhook handlers for Stripe events

### Phase 7: API Routes - COMPLETE
- [x] Create matters list/search endpoints
- [x] Build document scanning endpoints
- [x] Implement job status/progress endpoints
- [x] Create witness search/filter endpoints
- [x] Build export download endpoints

### Phase 8: Deployment - COMPLETE
- [x] Create railway.json for Railway
- [x] Set up Celery worker configuration
- [x] Create deployment documentation
- [x] Railway project created with PostgreSQL
- [x] GitHub repository connected
- [ ] Add monitoring and alerting (future)

---

## Technical Specifications

### Clio API Details
- **Client ID:** `PKQa4hMGOIYyYHcnuwiIW75Dy4Lwj3zNwGnBfLSq`
- **App ID:** 25010
- **OAuth Endpoints:**
  - Authorize: `https://app.clio.com/oauth/authorize`
  - Token: `https://app.clio.com/oauth/token`
- **API Base:** `https://app.clio.com/api/v4`
- **Rate Limit:** 50 requests/minute
- **Scopes:** matters:read, documents:read, contacts:read (full permissions granted)

### AWS Bedrock Configuration
- **Model ID:** `anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Region:** us-east-1
- **Image Limits:** 3.75MB max, 8000px max dimension
- **API:** InvokeModel with Messages API format

### Database Schema (PostgreSQL)
- `users` - Firebase UID, subscription, Stripe customer ID
- `clio_integrations` - Encrypted OAuth tokens per user
- `matters` - Synced from Clio
- `documents` - Processed documents with caching
- `witnesses` - Extracted witness data
- `processing_jobs` - Background job tracking

### Security Requirements
- Fernet encryption for OAuth tokens at rest
- Zero-retention for document content (ephemeral processing)
- TLS 1.3 for all API communication
- AWS KMS for key management (production)

---

## CLI Tools Available
- **Railway CLI:** `railway` (logged in)
- **Firebase CLI:** `firebase` (logged in)
- **Stripe CLI:** `stripe` (logged in as Juridion Labs)
- **GitHub CLI:** `gh` (logged in as jeebus87)
- **Gemini CLI:** Available for AI brainstorming

---

## Progress Tracking

Last Updated: 2026-01-14

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: Backend Foundation | COMPLETE | 100% |
| Phase 2: Clio OAuth | COMPLETE | 100% |
| Phase 3: Document Processing | COMPLETE | 100% |
| Phase 4: AI Witness Extraction | COMPLETE | 100% |
| Phase 5: Export Generation | COMPLETE | 100% |
| Phase 6: Firebase & Stripe | PENDING | 0% |
| Phase 7: API Routes | COMPLETE | 100% |
| Phase 8: Deployment | COMPLETE | 90% |

**Overall Backend Progress: 90%**

Remaining work:
- Firebase Auth integration (can use placeholder auth for now)
- Stripe billing integration
- Production environment variables configuration

---

## Quick Start

```bash
# Clone repository
git clone https://github.com/jeebus87/AIWitnessOrganizer.git
cd AIWitnessOrganizer

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your credentials

# Generate Fernet key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload

# Start Celery worker (separate terminal)
celery -A app.worker.celery worker --loglevel=info
```

---

## Railway Deployment

```bash
# Link to Railway project
railway link

# Deploy
railway up

# View logs
railway logs

# Set environment variables
railway variables --set CLIO_CLIENT_SECRET=YlKoOGlNxczG0xPhnTk6Qx5SwJvDNDpKUIWotiFp
```
