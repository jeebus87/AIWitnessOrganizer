# Privilege Detection & Privilege Log Architecture

## Status: PLANNED (Not Yet Implemented)

This document outlines the architecture for detecting privileged documents and generating privilege logs. Implementation will begin after testing current features.

---

## Overview

### Problem
Currently, all documents are processed identically without filtering for:
- Attorney-client privilege
- Work product doctrine
- Common interest privilege

This risks privileged information making it into pleadings or being disclosed.

### Solution
Add privilege detection as a **gateway** before witness extraction, with:
- AI-powered privilege classification
- Human review queue for uncertain cases
- Automated privilege log generation
- Integration with Clio for document management

---

## Architecture

### Workflow Diagram

```
Document Sync from Clio
        ↓
┌─────────────────────────────────────┐
│   PRIVILEGE DETECTION (AI Pass 1)   │  ← Before witness extraction
│   Claude/Bedrock analyzes document  │
└─────────────────────────────────────┘
        ↓
   ┌────┴────┐
   │ Routing │
   └────┬────┘
        ↓
   ┌────────────────┬─────────────────┬──────────────────┐
   │ NOT PRIVILEGED │ NEEDS REVIEW    │ PRIVILEGED       │
   │ (High conf)    │ (Med conf)      │ (High conf)      │
   │     ↓          │     ↓           │     ↓            │
   │ Witness        │ Human Review    │ Skip witness     │
   │ Extraction     │ Queue           │ extraction       │
   │     ↓          │     ↓           │ Store metadata   │
   │ Normal flow    │ Manual decision │ Add to priv log  │
   └────────────────┴─────────────────┴──────────────────┘
```

### Confidence Thresholds

| Confidence Score | Action |
|------------------|--------|
| > 95% NOT privileged | Auto-proceed to witness extraction |
| > 95% IS privileged | Auto-flag, skip extraction, add to log |
| 60% - 95% | Queue for human review |
| < 60% | Create new record, needs review |

---

## Database Schema

### New Table: `privileged_documents`

```sql
CREATE TABLE privileged_documents (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    matter_id INTEGER REFERENCES matters(id),
    organization_id INTEGER REFERENCES organizations(id),

    -- Privilege classification
    privilege_status VARCHAR(50) NOT NULL DEFAULT 'pending',
        -- 'pending', 'not_privileged', 'needs_review', 'confirmed_privileged'
    privilege_type VARCHAR(100),
        -- 'attorney_client', 'work_product', 'common_interest', 'none'
    confidence_score FLOAT,

    -- AI analysis
    ai_justification TEXT,
    partial_privilege_sections JSONB,  -- For partially privileged docs

    -- Human review
    reviewed_by_user_id INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    human_justification TEXT,

    -- Privilege log fields (for confirmed privileged docs)
    log_control_number VARCHAR(50),  -- 'PRIV_000001'
    document_date DATE,
    authors TEXT[],
    recipients TEXT[],
    document_type VARCHAR(100),  -- 'Email', 'Memorandum', 'Draft Pleading'
    subject_title VARCHAR(500),
    basis_for_privilege TEXT,  -- Final justification for log

    -- Clio integration
    clio_privilege_folder_id VARCHAR(128),  -- Where copy was placed

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_priv_docs_matter ON privileged_documents(matter_id);
CREATE INDEX idx_priv_docs_status ON privileged_documents(privilege_status);
CREATE INDEX idx_priv_docs_org ON privileged_documents(organization_id);
```

### Modify Existing `Witness` Table

Add field to track if witness came from privileged source:

```sql
ALTER TABLE witnesses ADD COLUMN source_is_privileged BOOLEAN DEFAULT FALSE;
```

---

## Privilege Log Standard Format

### Required Fields

| Field | Description | Example |
|-------|-------------|---------|
| **Control Number** | Unique Bates-style ID | PRIV_000001 |
| **Date** | Document creation date | 2025-03-15 |
| **Author(s)** | Name and organization | Jane Doe, Esq. (Smith & Jones LLP) |
| **Recipient(s)** | To/CC/BCC with orgs | John Client (Acme Corp) |
| **Document Type** | Neutral description | Email |
| **Subject/Title** | Subject line or title | Re: Legal advice on merger |
| **Privilege Asserted** | Type of privilege | Attorney-Client Privilege |
| **Basis for Privilege** | Why privileged (no content) | Confidential communication between counsel and client for purpose of seeking legal advice |

### Output Formats

- **Primary:** Word (.docx) - editable for attorney review
- **Secondary:** PDF - non-editable for formal production
- **Optional:** Excel/CSV - for sorting and filtering

### Naming Convention

```
Privilege Log - [Matter Name] - YYYY-MM-DD_v[N].docx
Privilege Log - Acme Corp v. Beta Inc - 2026-01-17_v1.docx
```

Always version, never overwrite (maintains audit trail).

---

## Privilege Detection Indicators

### Attorney-Client Privilege

| Indicator | Examples |
|-----------|----------|
| **Participants** | Law firm email domains (@sullcrom.com), "Esq.", "Counsel", "Attorney" |
| **Keywords** | "Legal advice", "confidential", "privileged communication", "attorney-client" |
| **Content** | Client asking lawyer for advice; lawyer providing analysis/recommendations |

### Work Product Doctrine

| Indicator | Examples |
|-----------|----------|
| **Participants** | Internal law firm comms, attorney to expert/investigator |
| **Keywords** | "In anticipation of litigation", "trial preparation", "case strategy", "draft brief" |
| **Content** | Analysis of facts, legal theories, discovery plans, draft pleadings |

### Common Interest Privilege

| Indicator | Examples |
|-----------|----------|
| **Participants** | Multiple parties' attorneys in same communication |
| **Keywords** | "Joint defense agreement", "JDA", "common interest" |
| **Content** | Shared legal strategy between parties with common legal interest |

---

## AI Prompt Structure

```
You are an expert paralegal with 20 years of experience in e-discovery and
privilege review for complex litigation in the United States. Your task is
to analyze the following document and determine if it is subject to
attorney-client privilege, the work product doctrine, or the common interest
privilege.

**Definitions to use:**
- **Attorney-Client Privilege:** Protects confidential communications between
  an attorney and their client made for the purpose of providing or obtaining
  legal advice.
- **Work Product Doctrine:** Protects materials prepared by or for an attorney
  in anticipation of litigation. This includes mental impressions, strategies,
  and legal theories.
- **Common Interest Privilege:** Extends attorney-client privilege to
  communications shared between parties with a common legal interest.

**Analysis Steps:**
1. Read the entire document carefully.
2. Identify all authors and recipients. Note if any are explicitly identified
   as attorneys or work for law firms.
3. Analyze the content for keywords and context related to legal advice or
   litigation strategy.
4. Determine if the document meets the criteria for any of the defined privileges.
5. If the document contains both privileged and non-privileged information,
   identify the specific sentences or paragraphs that are privileged.

**Output Format:**
Provide your response ONLY in the following JSON format:

{
  "is_privileged": <true or false>,
  "privilege_type": <"attorney_client", "work_product", "common_interest", or "none">,
  "confidence_score": <float between 0.0 and 1.0>,
  "justification": "<Concise explanation for determination>",
  "partial_privilege_sections": [
    "<Exact text of privileged section 1, if any>",
    "<Exact text of privileged section 2, if any>"
  ],
  "detected_attorneys": ["<Name 1>", "<Name 2>"],
  "detected_clients": ["<Name 1>", "<Name 2>"],
  "document_date": "<YYYY-MM-DD if determinable>",
  "document_type": "<Email, Memorandum, Letter, etc.>"
}

**Document to Analyze:**
---
[DOCUMENT TEXT HERE]
---
```

---

## Clio Integration

### Folder Structure

Auto-create within each Matter:

```
[Matter Name]/
├── (user's existing folders - DO NOT MODIFY)
└── ⚖️ AI Witness Finder - Privilege Review/
    ├── 1 - Documents for Review/     ← Copies needing human review
    ├── 2 - Confirmed Privileged/     ← Copies of confirmed privileged docs
    └── 3 - Privilege Logs/           ← Generated log documents
```

### Workflow Rules

1. **Never move or modify** original documents in Clio
2. **Copy** documents to privilege folders (original stays in place)
3. **Database is source of truth** - Clio folders are convenience views
4. Generate logs **on-demand** from database, save to Clio

---

## Handling Witnesses from Privileged Documents

### Recommendation: Extract but Segregate

Even privileged documents may mention key witnesses. The approach:

1. **Extract witnesses** from privileged documents
2. **Flag them** with `source_is_privileged: true`
3. **Store separately** - can be excluded from exports
4. **UI treatment:**
   - Display with lock icon
   - Show "Source: Privileged Document - [Filename]"
   - Don't show actual privileged content/quotes

This maintains the witness timeline while protecting privileged content.

---

## Libraries & Dependencies

### Python Libraries to Add

```
python-docx>=0.8.11    # Word document generation
WeasyPrint>=52.0       # HTML to PDF conversion (alternative: ReportLab)
openpyxl>=3.0.0        # Excel export
```

### Existing Libraries (Already Available)

- `boto3` - AWS Bedrock for AI analysis
- `httpx` - Clio API calls
- `sqlalchemy` - Database operations

---

## Implementation Phases

### Phase 1: Database & Models
- [ ] Add `privileged_documents` table
- [ ] Add `source_is_privileged` to witnesses
- [ ] Create migration scripts

### Phase 2: Privilege Detection Service
- [ ] Create `app/services/privilege_detection_service.py`
- [ ] Add privilege detection prompt to Bedrock client
- [ ] Integrate into document processing pipeline (before witness extraction)

### Phase 3: Human Review Queue
- [ ] Add API endpoints for review queue
- [ ] Create frontend review interface
- [ ] Allow confirm/deny/edit privilege status

### Phase 4: Privilege Log Generation
- [ ] Create `app/services/privilege_log_service.py`
- [ ] Word document template with python-docx
- [ ] PDF export option
- [ ] Excel/CSV export option

### Phase 5: Clio Integration
- [ ] Auto-create privilege folder structure
- [ ] Copy confirmed privileged docs to Clio folder
- [ ] Upload generated logs to Clio

### Phase 6: Frontend Updates
- [ ] Privilege status indicators on documents
- [ ] Review queue UI
- [ ] Generate log button
- [ ] Witness display for privileged sources

---

## Files to Create

| File | Purpose |
|------|---------|
| `app/services/privilege_detection_service.py` | AI privilege analysis |
| `app/services/privilege_log_service.py` | Log generation (DOCX/PDF) |
| `app/api/v1/routes/privilege.py` | API endpoints |
| `app/api/v1/schemas/privilege.py` | Pydantic schemas |
| `migrations/add_privilege_tables.sql` | Database migration |
| `frontend/src/app/(authenticated)/privilege/` | Review UI |

## Files to Modify

| File | Changes |
|------|---------|
| `app/db/models.py` | Add PrivilegedDocument model |
| `app/worker/tasks.py` | Add privilege check before witness extraction |
| `app/services/clio_client.py` | Add folder creation, document upload |
| `requirements.txt` | Add python-docx, WeasyPrint |

---

## Security Considerations

1. **Never log privileged content** - only metadata
2. **Encrypt privileged document storage** if caching locally
3. **Audit trail** - log all privilege determinations and who reviewed
4. **Access control** - only authorized users can view privileged docs
5. **No external APIs** for privileged content (keep in Bedrock/internal)

---

## References

- Gemini consultation: January 2026
- Standard privilege log formats per Federal Rules of Civil Procedure
- Work product doctrine: Hickman v. Taylor, 329 U.S. 495 (1947)
