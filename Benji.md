# AIWitnessFinder Processing System Optimization Plan

## Implementation Status (Updated 2026-01-17)

### Phase 1: Smart Document Processing - IMPLEMENTED (needs testing)
| Task | Status | Notes |
|------|--------|-------|
| Hybrid PDF Processing (PyMuPDF) | ✅ IMPLEMENTED | `_process_pdf_hybrid()` in document_processor.py |
| Content Hash Caching | ✅ IMPLEMENTED | `content_hash` column + check in tasks.py |
| Migration 015 (content_hash) | ✅ RAN ON RAILWAY | Database updated |

### Phase 2: Clio Webhooks - IMPLEMENTED (needs testing)
| Task | Status | Notes |
|------|--------|-------|
| Webhook Endpoints | ✅ IMPLEMENTED | `app/api/v1/routes/webhooks.py` |
| ClioWebhookSubscription Model | ✅ IMPLEMENTED | Added to models.py |
| Clio Client webhook methods | ✅ IMPLEMENTED | subscribe_to_webhook, renew_webhook, delete_webhook |
| Webhook config settings | ✅ IMPLEMENTED | CLIO_WEBHOOK_SECRET, CLIO_WEBHOOK_BASE_URL |
| Migration 018 (webhook_subscriptions) | ✅ RAN ON RAILWAY | Database updated |

### Phase 3: Witness Deduplication - IMPLEMENTED (needs testing)
| Task | Status | Notes |
|------|--------|-------|
| CanonicalWitness Model | ✅ IMPLEMENTED | Added to models.py |
| DeduplicationService | ✅ IMPLEMENTED | app/services/deduplication_service.py |
| Migration 016 (canonical_witnesses) | ✅ RAN ON RAILWAY | Database updated |
| thefuzz dependency | ✅ ADDED | requirements.txt |

### Phase 4: Relevancy System - IMPLEMENTED (needs testing)
| Task | Status | Notes |
|------|--------|-------|
| CaseClaim Model | ✅ IMPLEMENTED | Added to models.py |
| WitnessClaimLink Model | ✅ IMPLEMENTED | Added to models.py |
| ClaimsService | ✅ IMPLEMENTED | app/services/claims_service.py |
| Bedrock claims extraction | ✅ IMPLEMENTED | extract_claims() in bedrock_client.py |
| Relevancy API endpoints | ✅ IMPLEMENTED | app/api/v1/routes/relevancy.py |
| Export with relevancy section | ✅ IMPLEMENTED | generate_pdf_with_relevancy() |
| Migration 017 (case_claims + links) | ✅ RAN ON RAILWAY | Database updated |

### All Migrations Completed:
```bash
# All migrations have been run on Railway database:
# 015 - content_hash column ✅
# 016 - canonical_witnesses table ✅
# 017 - case_claims + witness_claim_links tables ✅
# 018 - clio_webhook_subscriptions table ✅
```

### New Dependencies Added:
```
PyMuPDF>=1.24.0
thefuzz>=0.22.1
python-Levenshtein>=0.25.0
```

### Remaining Tasks:
| Task | Status | Priority |
|------|--------|----------|
| DOCX Export | ✅ IMPLEMENTED | LOW |
| Frontend Relevancy UI | ⏳ PENDING | MEDIUM |
| End-to-end testing | ⏳ PENDING | HIGH |

### DOCX Export Details:
- `generate_docx()` method in export_service.py
- `generate_docx_with_relevancy()` method for full reports
- Same content structure as PDF export
- Editable Word format preferred by lawyers

---

## Executive Summary

Comprehensive optimization plan to improve processing efficiency, reduce costs, and enhance user experience. Key improvements:

1. **55-60% reduction in AI token usage** via hybrid PDF processing (text extraction with vision fallback)
2. **Skip unchanged documents** via content hash caching
3. **Real-time document sync** via Clio webhooks (eliminate polling)
4. **Cross-document witness deduplication** for cleaner reports
5. **DOCX export** for lawyer convenience

---

## Current System Analysis

### Processing Pipeline:
```
Clio API (poll) → Download → PDF-to-Image (pdf2image @ 100 DPI)
    → Claude Vision Extract → Claude Vision Verify → Store Witnesses
```

### Folder Selection (PRESERVED - NO CHANGES)

**Current behavior that MUST be preserved:**

1. **User selects folder to scan** via `scan_folder_id` - only documents in that folder are processed
2. **Legal Authority folder exclusion** via `legal_authority_folder_id` - excluded from witness extraction
3. **Subfolder recursion** via `include_subfolders` toggle
4. **Document snapshot** via `document_ids_snapshot` - freezes document list at job start

**Code locations (unchanged by this plan):**
- `app/api/v1/routes/matters.py:359-390` - Folder filtering in process_matter endpoint
- `app/worker/tasks.py:656-668` - Folder filtering during document selection
- `app/db/models.py:211` - `clio_folder_id` stored on each document

**These optimizations ONLY affect HOW documents are processed, NOT WHICH documents are selected.**

### Identified Bottlenecks:
| Issue | Impact | Solution |
|-------|--------|----------|
| All PDFs → images | Expensive tokens | Hybrid: text first, vision fallback |
| No content caching | Re-processes unchanged docs | SHA-256 hash check |
| Full sync every time | Slow, API heavy | Clio webhooks |
| Double AI calls | 2x token cost | Keep (accuracy critical) |
| No deduplication | Same witness appears multiple times | Fuzzy name matching |

### Key Files:
- `app/worker/tasks.py` - Processing orchestration (1155 lines)
- `app/services/document_processor.py` - PDF/doc conversion (907 lines)
- `app/services/bedrock_client.py` - Claude AI extraction (783 lines)
- `app/services/clio_client.py` - Clio API integration (710 lines)
- `app/services/export_service.py` - PDF/Excel exports (651 lines)

---

## Phase 1: Smart Document Processing (HIGH PRIORITY)

### 1.1 Hybrid PDF Processing with PyMuPDF

**Goal:** Extract text from text-based PDFs, use vision only for scanned pages.

**Token Savings:**
- Vision (current): ~62,350 tokens for 50-page doc
- Text (proposed): ~26,600 tokens for same doc
- **55-60% reduction!**

**File:** `app/services/document_processor.py`

```python
import fitz  # PyMuPDF

async def _process_pdf_hybrid(self, content: bytes, filename: str, context: str = "") -> List[ProcessedAsset]:
    """
    Hybrid PDF: extract text first, fall back to vision for scanned pages.
    CRITICAL: Preserves exact page numbers for each asset.
    """
    assets = []
    doc = fitz.open(stream=content, filetype="pdf")

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()

        # Detect if page is scanned (low text density)
        rect = page.rect
        page_area = rect.width * rect.height
        text_density = len(text) / page_area if page_area > 0 else 0

        if len(text) > 100 and text_density > 0.1:
            # Text-based page: use extracted text (MUCH cheaper)
            assets.append(ProcessedAsset(
                asset_type="text",
                content=text.encode("utf-8"),
                media_type="text/plain",
                filename=f"{filename}_page_{page_num + 1}.txt",
                page_number=page_num + 1  # CRITICAL: exact page
            ))
        else:
            # Scanned page: fall back to vision
            pix = page.get_pixmap(dpi=100)
            assets.append(ProcessedAsset(
                asset_type="image",
                content=pix.tobytes("jpeg"),
                media_type="image/jpeg",
                filename=f"{filename}_page_{page_num + 1}.jpg",
                page_number=page_num + 1  # CRITICAL: exact page
            ))

    doc.close()
    return assets
```

**Complexity:** Medium (2-3 days)
**New Dependency:** `PyMuPDF>=1.24.0`

### 1.2 Content Hash Caching

**Goal:** Skip processing for unchanged documents.

**File:** `app/db/models.py` - Add column:
```python
class Document(Base):
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256
```

**File:** `app/worker/tasks.py` - Check before processing:
```python
# Calculate hash BEFORE processing
content_hash = hashlib.sha256(content).hexdigest()

# Skip if unchanged and already processed
if document.content_hash == content_hash and document.is_processed:
    logger.info(f"Document {doc_id} unchanged, skipping")
    return {"success": True, "cached": True, "tokens_used": 0}

# Store hash for future
document.content_hash = content_hash
```

**Complexity:** Low (1 day)

### 1.3 Page Number Tracking (CRITICAL)

**CRITICAL REQUIREMENT:** Must extract exact page numbers for ALL document types. This is non-negotiable for legal discovery.

#### Page Number Strategy by Document Type:

| Document Type | Current | Proposed | Accuracy |
|--------------|---------|----------|----------|
| PDF (text) | Via pdf2image page index | PyMuPDF page-by-page | **Exact** |
| PDF (scanned) | Via pdf2image page index | PyMuPDF get_pixmap per page | **Exact** |
| DOCX | None tracked | **Convert to PDF first** via LibreOffice/docx2pdf | **Exact** |
| Email body | None | Set `page_number=1` | **Exact** |
| Email attachments | None | Process separately, track by attachment | **Per-attachment** |
| XLSX | None | Sheet number as page | **By sheet** |
| PPTX | None | Slide number as page | **By slide** |
| TXT/HTML | None | Set `page_number=1` | Single page |

#### Implementation Details:

**PDFs (Hybrid Processing):**
```python
for page_num in range(len(doc)):
    page = doc[page_num]
    # page_num + 1 for human-readable (1-indexed)
    asset.page_number = page_num + 1
```

**DOCX - Convert to PDF for Page Numbers:**
```python
async def _process_docx_with_pages(self, content: bytes, filename: str) -> List[ProcessedAsset]:
    """Convert DOCX to PDF to get accurate page numbers, then process."""
    import subprocess
    import tempfile

    # Write DOCX to temp file
    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
        f.write(content)
        docx_path = f.name

    # Convert to PDF using LibreOffice (headless)
    pdf_path = docx_path.replace('.docx', '.pdf')
    subprocess.run([
        'libreoffice', '--headless', '--convert-to', 'pdf',
        '--outdir', os.path.dirname(docx_path), docx_path
    ], check=True, timeout=120)

    # Process the PDF (which has accurate page numbers)
    with open(pdf_path, 'rb') as f:
        pdf_content = f.read()

    return await self._process_pdf_hybrid(pdf_content, filename)
```

**Alternative for DOCX (if LibreOffice unavailable):**
```python
# Use python-docx to extract text, estimate pages by word count
# ~500 words per page average for legal documents
WORDS_PER_PAGE = 500

def estimate_page_number(text: str, position: int) -> int:
    words_before = len(text[:position].split())
    return (words_before // WORDS_PER_PAGE) + 1
```

**Emails (MSG/EML):**
```python
async def _process_email(self, content: bytes, filename: str) -> List[ProcessedAsset]:
    assets = []

    # Email body is always page 1
    body_text = extract_email_body(content)
    assets.append(ProcessedAsset(
        asset_type="text",
        content=body_text.encode(),
        page_number=1,  # Body is page 1
        context="Email body"
    ))

    # Attachments tracked separately with their own page numbers
    for i, attachment in enumerate(extract_attachments(content)):
        attachment_assets = await self.process_file(
            attachment.content,
            f"{filename}_attachment_{i+1}_{attachment.name}"
        )
        # Each attachment starts at page 1 within itself
        # Source will show: "email.msg (Attachment: doc.pdf, Page 3)"
        for asset in attachment_assets:
            asset.context = f"Attachment: {attachment.name}"
        assets.extend(attachment_assets)

    return assets
```

**XLSX (Excel):**
```python
async def _process_xlsx(self, content: bytes, filename: str) -> List[ProcessedAsset]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assets = []

    for sheet_num, sheet_name in enumerate(wb.sheetnames, 1):
        sheet = wb[sheet_name]
        text = extract_sheet_text(sheet)
        assets.append(ProcessedAsset(
            asset_type="text",
            content=text.encode(),
            page_number=sheet_num,  # Sheet number as page
            context=f"Sheet: {sheet_name}"
        ))

    return assets
```

**Source Citation Format in Exports:**
```
Standard:     "document.pdf (Page 5)"
Email:        "email.msg (Page 1)" or "email.msg (Attachment: exhibit.pdf, Page 3)"
Excel:        "data.xlsx (Sheet 2: Revenue)"
PowerPoint:   "presentation.pptx (Slide 7)"
```

**File:** `app/services/document_processor.py` - Update all methods to include page_number

**New Dependency for DOCX:** Either:
- LibreOffice (headless) for accurate conversion, OR
- `docx2pdf>=0.1.8` Python library

---

## Phase 2: Clio Webhook Integration (MEDIUM PRIORITY)

**Goal:** Real-time document sync instead of polling.

### Clio Webhook Capabilities (from research):
- Events: `document.create`, `document.update`, `document.delete`
- HTTPS required
- Max lifetime: 31 days (requires renewal)
- Signature verification via HMAC-SHA256

### New File: `app/api/v1/routes/webhooks.py`

```python
@router.post("/clio")
async def clio_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Clio document webhooks for real-time sync."""
    payload = await request.body()
    signature = request.headers.get("X-Hook-Signature")

    # Verify signature
    if not verify_clio_signature(payload, signature, settings.clio_webhook_secret):
        raise HTTPException(401, "Invalid signature")

    data = await request.json()
    event_type = data.get("type")
    clio_doc_id = str(data["data"]["id"])

    if event_type == "document.create":
        sync_single_document.delay(clio_doc_id)
    elif event_type == "document.update":
        sync_single_document.delay(clio_doc_id, force_reprocess=False)
    elif event_type == "document.delete":
        delete_document_local.delay(clio_doc_id)

    return {"status": "received"}
```

### New File: `app/db/models.py` - Add:

```python
class ClioWebhookSubscription(Base):
    """Track webhook subscriptions (expire after 31 days)"""
    __tablename__ = "clio_webhook_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    clio_subscription_id = Column(String(128), unique=True)
    event_type = Column(String(50))  # document.create, etc.
    webhook_url = Column(String(512))
    secret = Column(String(255))  # HMAC secret
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
```

### Clio Client Updates: `app/services/clio_client.py`

```python
async def subscribe_to_webhooks(self, callback_url: str) -> List[Dict]:
    """Subscribe to document.create, document.update, document.delete"""

async def renew_webhook(self, subscription_id: str) -> Dict:
    """Renew before 31-day expiration"""
```

**Complexity:** Medium-High (3-4 days)

---

## Phase 3: Cross-Document Witness Deduplication (MEDIUM PRIORITY)

**Goal:** Consolidate same witness mentioned across multiple documents.

### New File: `app/services/deduplication_service.py`

```python
from thefuzz import fuzz

class DeduplicationService:
    NAME_SIMILARITY_THRESHOLD = 85  # 0-100

    def names_match(self, name1: str, name2: str) -> Tuple[bool, int]:
        """Fuzzy match using multiple algorithms."""
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        scores = [
            fuzz.ratio(norm1, norm2),
            fuzz.partial_ratio(norm1, norm2),
            fuzz.token_sort_ratio(norm1, norm2),
        ]
        best_score = max(scores)
        return best_score >= self.NAME_SIMILARITY_THRESHOLD, best_score

    async def deduplicate_matter_witnesses(self, matter_id: int) -> Dict:
        """
        Group witnesses by similarity, create canonical records.
        Merges observations from multiple documents.
        """
        # Get all witnesses for matter
        # Group by fuzzy name match
        # Create CanonicalWitness records
        # Link original Witness records to canonical
```

### New Model: `app/db/models.py`

```python
class CanonicalWitness(Base):
    """Deduplicated witness per matter"""
    __tablename__ = "canonical_witnesses"

    id = Column(Integer, primary_key=True)
    matter_id = Column(Integer, ForeignKey("matters.id"))
    full_name = Column(String(255))
    role = Column(Enum(WitnessRole))
    relevance = Column(Enum(RelevanceLevel))

    # Merged observations: [{doc_id, page, text}, ...]
    merged_observations = Column(JSON)

    # Best contact info from all sources
    email = Column(String(255))
    phone = Column(String(100))
    address = Column(Text)

    source_document_count = Column(Integer, default=1)


# Add to Witness model:
class Witness(Base):
    canonical_witness_id = Column(Integer, ForeignKey("canonical_witnesses.id"))
```

### Integration with Job Finalization:

```python
# In finalize_job(), after all documents processed:
if job.target_matter_id:
    deduplicate_matter_witnesses.delay(job.target_matter_id, job.id)
```

**Complexity:** Medium (2-3 days)
**New Dependency:** `thefuzz>=0.22.1`

---

## Phase 4: Export Enhancements (LOW PRIORITY)

### CRITICAL: Export Content Requirements

**DO NOT CHANGE existing export fields/variables:**
- Witness Info (name, role, contact)
- Relevance + Reason
- Confidence
- Observation (keep SPECIFIC and DETAILED - no summarization)
- Source Summary
- Source Document (with page number)

**MAY improve visual organization/appearance only.**

### 4.1 ADD: Relevancy Analysis Table

**Goal:** Add a new section showing WHY witnesses are relevant based on case allegations and defenses.

**New Section in PDF/Excel Exports:**

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                        RELEVANCY ANALYSIS                                     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ CASE ALLEGATIONS:                                                             ║
║ 1. Plaintiff alleges hostile work environment from Jan-Dec 2023               ║
║ 2. Plaintiff claims wrongful termination in retaliation                       ║
║ 3. Plaintiff alleges failure to accommodate disability                        ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ DEFENDANT'S DEFENSES:                                                         ║
║ 1. Termination was for documented performance issues                          ║
║ 2. No knowledge of disability; no accommodation request made                  ║
║ 3. Workplace conduct was consensual horseplay                                 ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ WITNESS RELEVANCY BREAKDOWN:                                                  ║
╠══════════════════╦══════════════════════════════════════════════════════════╣
║ Witness          ║ Relevant To                                               ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║ John Smith       ║ Allegation #1 (eyewitness to workplace conduct)          ║
║                  ║ Defense #3 (participated in alleged "horseplay")         ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║ Dr. Jane Doe     ║ Allegation #3 (treating physician, disability knowledge) ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║ HR Manager       ║ Allegation #2 (termination decision maker)               ║
║                  ║ Defense #1 (documented performance issues)               ║
╚══════════════════╩══════════════════════════════════════════════════════════╝
```

**Implementation:**

### Step 1: Extract Allegations/Defenses from Pleadings FIRST

**New Table:** `case_claims` - Central repository for allegations and defenses

```python
class CaseClaim(Base):
    """Central store for allegations and defenses extracted from case documents"""
    __tablename__ = "case_claims"

    id = Column(Integer, primary_key=True)
    matter_id = Column(Integer, ForeignKey("matters.id"), index=True)

    claim_type = Column(String(20))  # "allegation" or "defense"
    claim_number = Column(Integer)    # Sequential: Allegation #1, #2, etc.
    claim_text = Column(Text)         # "Hostile work environment from Jan-Dec 2023"

    # Source tracking
    source_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    source_page = Column(Integer, nullable=True)
    extraction_method = Column(String(20))  # "pleading", "discovery", "manual"

    confidence_score = Column(Float)
    is_verified = Column(Boolean, default=False)  # User confirmed

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
```

### Step 2: Processing Flow

```
1. USER UPLOADS COMPLAINT/ANSWER (Pleading Documents)
   ↓
   AI extracts numbered allegations and defenses
   ↓
   Store in case_claims table with extraction_method="pleading"
   ↓
2. USER REVIEWS/EDITS extracted claims (optional)
   ↓
3. USER PROCESSES DISCOVERY DOCUMENTS
   ↓
   AI references existing claims AND identifies new ones
   ↓
   New claims added with extraction_method="discovery"
   ↓
4. EXPORT includes full relevancy table
```

### Step 3: AI Prompt for Pleading Extraction

```python
PLEADING_EXTRACTION_PROMPT = """
Analyze this legal pleading document and extract:

1. ALLEGATIONS (if Complaint/Petition):
   - Number each allegation sequentially
   - Extract the core factual claim
   - Note the page number where found

2. DEFENSES (if Answer/Response):
   - Number each defense/affirmative defense
   - Extract the core legal defense
   - Note the page number where found

Return JSON:
{
  "allegations": [
    {"number": 1, "text": "Hostile work environment from Jan-Dec 2023", "page": 5},
    {"number": 2, "text": "Wrongful termination in retaliation", "page": 7}
  ],
  "defenses": [
    {"number": 1, "text": "Termination for documented performance issues", "page": 3}
  ]
}
"""
```

### Step 4: Link Witnesses to Claims

```python
class WitnessClaimLink(Base):
    """Many-to-many: witnesses linked to specific allegations/defenses"""
    __tablename__ = "witness_claim_links"

    id = Column(Integer, primary_key=True)
    witness_id = Column(Integer, ForeignKey("witnesses.id"))
    case_claim_id = Column(Integer, ForeignKey("case_claims.id"))

    relevance_explanation = Column(Text)  # Why this witness relates to this claim
    supports_or_undermines = Column(String(20))  # "supports", "undermines", "neutral"

    created_at = Column(DateTime, server_default=func.now())
```

### Step 5: Updated Witness Extraction Prompt

```python
# Inject existing claims into witness extraction prompt:
WITNESS_EXTRACTION_WITH_CLAIMS = """
CASE CONTEXT:
Allegations:
{allegations_list}

Defenses:
{defenses_list}

For each witness found, specify:
1. Their relevance to specific allegations (by number)
2. Their relevance to specific defenses (by number)
3. Whether they support or undermine each claim

Return:
{
  "fullName": "John Smith",
  "claimLinks": [
    {"claimNumber": 1, "claimType": "allegation", "relationship": "supports",
     "explanation": "Eyewitness to workplace conduct in break room"},
    {"claimNumber": 3, "claimType": "defense", "relationship": "undermines",
     "explanation": "Email shows he was aware of disability"}
  ]
}
"""
```

### Step 6: Central Relevancy Reference View

**New UI Page:** `/matters/{id}/relevancy`

Displays:
- All allegations with linked witnesses
- All defenses with linked witnesses
- Which witnesses support vs undermine each claim
- Source documents for each claim

**API Endpoint:** `GET /api/v1/matters/{id}/relevancy`

```python
@router.get("/{matter_id}/relevancy")
async def get_matter_relevancy(matter_id: int, ...):
    """
    Get centralized relevancy analysis for a matter.
    Returns allegations, defenses, and all witness linkages.
    """
    return {
        "allegations": [...],  # With linked witnesses
        "defenses": [...],     # With linked witnesses
        "witness_summary": [...],  # Each witness with their claim links
        "unlinked_witnesses": [...]  # Witnesses not yet linked to claims
    }
```

### Step 7: Export Relevancy Section

```python
def _generate_relevancy_section(self, matter_id):
    """Generate the relevancy analysis section for exports."""
    claims = get_case_claims(matter_id)
    links = get_witness_claim_links(matter_id)

    # Build the table shown in the example above
    # Group by witness, show which claims they relate to
```

### 4.2 DOCX Export (Optional)

**Goal:** Lawyers prefer editable Word documents.

Same content as PDF, but in editable DOCX format.

**Complexity:**
- Relevancy Table: Medium (2 days) - requires UI for entering allegations/defenses
- DOCX Export: Low (1 day)

---

## Implementation Timeline

| Phase | Deliverables | Duration | Priority |
|-------|-------------|----------|----------|
| 1.1 | Hybrid PDF processing | 2-3 days | HIGH |
| 1.2 | Content hash caching | 1 day | HIGH |
| 2 | Clio webhooks | 3-4 days | MEDIUM |
| 3 | Witness deduplication | 2-3 days | MEDIUM |
| 4.1 | Relevancy System (claims extraction + linking) | 3-4 days | HIGH |
| 4.2 | Relevancy UI + Export | 2 days | HIGH |
| 4.3 | DOCX export | 1 day | LOW |

**Total: 14-18 days**

---

## New Dependencies

```txt
# requirements.txt additions:
PyMuPDF>=1.24.0        # PDF text extraction
thefuzz>=0.22.1        # Fuzzy string matching
python-Levenshtein>=0.25.0  # Faster fuzzy matching
```

---

## Database Migrations

### Migration 015: Content Hash
```python
def upgrade():
    op.add_column('documents', sa.Column('content_hash', sa.String(64)))
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
```

### Migration 016: Webhook Subscriptions
```python
def upgrade():
    op.create_table('clio_webhook_subscriptions', ...)
```

### Migration 017: Canonical Witnesses
```python
def upgrade():
    op.create_table('canonical_witnesses', ...)
    op.add_column('witnesses', sa.Column('canonical_witness_id', sa.Integer()))
```

---

## Configuration Additions

**File:** `app/core/config.py`

```python
class Settings(BaseSettings):
    # Clio Webhooks
    clio_webhook_secret: Optional[str] = None
    clio_webhook_base_url: Optional[str] = None

    # PDF Processing
    pdf_text_density_threshold: float = 0.1
    pdf_use_hybrid_processing: bool = True

    # Deduplication
    witness_name_similarity_threshold: int = 85
```

---

## Verification Checklist

### Phase 1 Testing:
- [ ] Text-based PDF returns text assets with correct page numbers
- [ ] Scanned PDF returns image assets with correct page numbers
- [ ] Mixed PDF correctly classifies each page
- [ ] Unchanged documents skip processing (hash match)
- [ ] Token usage reduced ~55% for text PDFs

### Phase 2 Testing:
- [ ] Webhook subscription created in Clio
- [ ] document.create triggers sync
- [ ] document.update triggers conditional sync
- [ ] document.delete soft-deletes locally
- [ ] Signature verification works

### Phase 3 Testing:
- [ ] "John Smith" matches "John A. Smith" (85%+ score)
- [ ] "Dr. Jane Doe" matches "Jane Doe PhD"
- [ ] Canonical records created for duplicates
- [ ] Observations merged correctly

### Phase 4 Testing:
- [ ] DOCX opens in Microsoft Word
- [ ] Table formatting correct
- [ ] Canonical witnesses exported properly

---

## Key Gemini Recommendations (Applied)

1. **Keep verification pass** - Accuracy tradeoff not worth single-pass
2. **Hybrid PDF processing** - Text first, vision fallback (not batch documents)
3. **Post-processing deduplication** - Not during extraction
4. **Fuzzy matching with thefuzz** - token_sort_ratio for name variations
5. **Content hash for caching** - SHA-256 before processing

---

## Files to Create

| File | Purpose |
|------|---------|
| `app/api/v1/routes/webhooks.py` | Clio webhook handlers |
| `app/api/v1/routes/relevancy.py` | Relevancy API endpoints |
| `app/services/deduplication_service.py` | Fuzzy name matching |
| `app/services/claims_service.py` | Extract/manage allegations and defenses |
| `frontend/src/app/(authenticated)/matters/[id]/relevancy/page.tsx` | Relevancy UI |
| `alembic/versions/015_*.py` | Content hash migration |
| `alembic/versions/016_*.py` | Webhook subscriptions |
| `alembic/versions/017_*.py` | Canonical witnesses |
| `alembic/versions/018_*.py` | Case claims + witness links |

## Files to Modify

| File | Changes |
|------|---------|
| `app/services/document_processor.py` | Add `_process_pdf_hybrid()`, DOCX-to-PDF conversion |
| `app/worker/tasks.py` | Add hash check, webhook tasks, dedup call, claims extraction |
| `app/services/clio_client.py` | Add webhook management |
| `app/services/bedrock_client.py` | Add pleading extraction prompt, inject claims into witness prompt |
| `app/services/export_service.py` | Add relevancy section, DOCX export |
| `app/db/models.py` | Add CaseClaim, WitnessClaimLink, CanonicalWitness, content_hash |
| `app/core/config.py` | Add new settings |
| `requirements.txt` | Add PyMuPDF, thefuzz |
