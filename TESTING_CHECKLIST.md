# AIWitnessFinder Testing Checklist

## Phase 1: Smart Document Processing

### 1.1 Hybrid PDF Processing
- [ ] **Text-based PDF**: Upload a text-based PDF and verify it extracts text (not images)
- [ ] **Scanned PDF**: Upload a scanned/image PDF and verify it falls back to vision processing
- [ ] **Mixed PDF**: Upload a PDF with some text pages and some scanned pages - verify each page is handled correctly
- [ ] **Page numbers**: Verify extracted witnesses have correct source page numbers

### 1.2 Content Hash Caching
- [ ] **First processing**: Process a document and note it completes normally
- [ ] **Re-process unchanged**: Process the same document again - should skip with "unchanged (hash match)" message
- [ ] **Modified document**: Update a document in Clio, re-process - should process again (hash changed)

---

## Phase 2: Clio Webhooks

### 2.1 Webhook Subscription
- [ ] **Subscribe to webhooks**: POST to `/api/v1/webhooks/subscribe` - verify subscriptions created
- [ ] **List subscriptions**: GET `/api/v1/webhooks/subscriptions` - verify subscriptions listed
- [ ] **Webhook secret**: Verify CLIO_WEBHOOK_SECRET and CLIO_WEBHOOK_BASE_URL are configured

### 2.2 Webhook Events (requires Clio test environment)
- [ ] **document.create**: Add a document in Clio - verify webhook received
- [ ] **document.update**: Update a document in Clio - verify local document marked for re-processing
- [ ] **document.delete**: Delete a document in Clio - verify local document soft-deleted

### 2.3 Webhook Management
- [ ] **Renew subscription**: POST `/api/v1/webhooks/subscriptions/{id}/renew` - verify extended
- [ ] **Delete subscription**: DELETE `/api/v1/webhooks/subscriptions/{id}` - verify removed

---

## Phase 3: Witness Deduplication

### 3.1 Fuzzy Name Matching
- [ ] **Exact match**: "John Smith" matches "John Smith" (100% score)
- [ ] **Middle name**: "John Smith" matches "John A. Smith" (should be 85%+)
- [ ] **Title variations**: "Dr. Jane Doe" matches "Jane Doe PhD" (should be 85%+)
- [ ] **Different names**: "John Smith" does NOT match "Jane Doe" (should be below threshold)

### 3.2 Canonical Witness Creation
- [ ] **Process multiple documents**: Process documents mentioning same witness with slight name variations
- [ ] **Verify deduplication**: Check `canonical_witnesses` table has merged records
- [ ] **Observations merged**: Verify `merged_observations` JSON contains all source observations
- [ ] **Source count**: Verify `source_document_count` reflects number of source documents

---

## Phase 4: Relevancy System

### 4.1 Case Claims API
- [ ] **Add allegation**: POST `/api/v1/relevancy/{matter_id}/claims` with type="allegation"
- [ ] **Add defense**: POST `/api/v1/relevancy/{matter_id}/claims` with type="defense"
- [ ] **List claims**: GET `/api/v1/relevancy/{matter_id}/claims` - verify both types listed
- [ ] **Update claim**: PUT `/api/v1/relevancy/{matter_id}/claims/{id}` - verify updated
- [ ] **Delete claim**: DELETE `/api/v1/relevancy/{matter_id}/claims/{id}` - verify removed
- [ ] **Auto-numbering**: Verify claim_number increments correctly per type per matter

### 4.2 Witness-Claim Links
- [ ] **Link witness to claim**: POST `/api/v1/relevancy/{matter_id}/witness-links`
- [ ] **Supports/undermines**: Verify relationship field stored correctly
- [ ] **Relevance explanation**: Verify explanation text saved

### 4.3 Relevancy Analysis API
- [ ] **Get full analysis**: GET `/api/v1/relevancy/{matter_id}`
- [ ] **Allegations with witnesses**: Verify allegations include linked_witnesses array
- [ ] **Defenses with witnesses**: Verify defenses include linked_witnesses array
- [ ] **Witness summary**: Verify witness_summary shows claim links per witness
- [ ] **Unlinked witnesses**: Verify unlinked_witnesses lists witnesses without claim links

### 4.4 AI Claims Extraction (if implemented)
- [ ] **Extract from pleading**: Upload complaint/answer and verify AI extracts claims
- [ ] **Confidence scores**: Verify extracted claims have confidence scores

---

## Phase 5: Export Enhancements

### 5.1 DOCX Export
- [ ] **Generate DOCX**: Call `generate_docx()` method and download file
- [ ] **Opens in Word**: Verify DOCX opens correctly in Microsoft Word
- [ ] **Cover page**: Verify cover page has matter name, firm, date
- [ ] **Witness table**: Verify table has all 6 columns with correct data
- [ ] **Row colors**: Verify relevance-based row coloring (red=high, yellow=medium, green=low)

### 5.2 DOCX with Relevancy
- [ ] **Generate with relevancy**: Call `generate_docx_with_relevancy()`
- [ ] **Allegations table**: Verify allegations section with linked witnesses
- [ ] **Defenses table**: Verify defenses section with linked witnesses
- [ ] **Witness breakdown**: Verify witness relevancy breakdown table

### 5.3 PDF with Relevancy
- [ ] **Generate with relevancy**: Call `generate_pdf_with_relevancy()`
- [ ] **Relevancy section**: Verify new relevancy analysis section appears after witness table

---

## Phase 6: Frontend Relevancy UI

### 6.1 Page Access
- [ ] **Navigate to page**: Go to `/matters/{id}/relevancy` - page loads without errors
- [ ] **Back button**: Click back button - returns to previous page

### 6.2 Allegations Section
- [ ] **Display allegations**: Verify allegations table shows all allegations
- [ ] **Linked witnesses**: Verify witnesses shown with supports/undermines badges
- [ ] **Delete allegation**: Click delete - allegation removed

### 6.3 Defenses Section
- [ ] **Display defenses**: Verify defenses table shows all defenses
- [ ] **Linked witnesses**: Verify witnesses shown with relationship badges
- [ ] **Delete defense**: Click delete - defense removed

### 6.4 Add Claim Dialog
- [ ] **Open dialog**: Click "Add Claim" button - dialog opens
- [ ] **Select type**: Can select Allegation or Defense
- [ ] **Enter text**: Can enter claim text
- [ ] **Submit**: Click Add - claim added and appears in list
- [ ] **Cancel**: Click Cancel - dialog closes without adding

### 6.5 Witness Summary
- [ ] **Display summary**: Verify witness summary table shows all witnesses
- [ ] **Claim links**: Verify each witness shows their claim links
- [ ] **Unlinked witnesses**: Verify unlinked witnesses shown in separate section

---

## Database Migrations

### Verify All Tables Exist
- [ ] `documents.content_hash` column exists
- [ ] `canonical_witnesses` table exists
- [ ] `witnesses.canonical_witness_id` column exists
- [ ] `case_claims` table exists
- [ ] `witness_claim_links` table exists
- [ ] `clio_webhook_subscriptions` table exists

---

## Testing Progress

| Feature | Status | Notes |
|---------|--------|-------|
| Hybrid PDF - Text | | |
| Hybrid PDF - Scanned | | |
| Content Hash Cache | | |
| Webhook Subscribe | | |
| Deduplication | | |
| Claims API | | |
| Witness Links | | |
| DOCX Export | | |
| Frontend UI | | |

---

## How to Test

1. Start with **database migrations** - verify all tables exist
2. Test **Phase 1** - upload different PDF types
3. Test **Phase 3** - process documents with duplicate witnesses
4. Test **Phase 4** - use API to add claims and links
5. Test **Phase 5** - generate exports
6. Test **Phase 6** - use frontend UI
7. Test **Phase 2** last (requires webhook configuration)
