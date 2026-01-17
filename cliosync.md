# Clio Sync Refactor Plan (with Concurrency)

## Research Summary

**Clio API Rate Limits:** ([source](https://docs.developers.clio.com/api-docs/rate-limits/))
- 50 requests/minute during peak hours
- Rate limited per access token
- Returns 429 with `Retry-After` header when exceeded

**Gemini's Concurrency Recommendations:**
1. Add `sync_status` to Matter (IDLE/SYNCING/FAILED) as a lock
2. Add `document_ids_snapshot` to ProcessingJob - freeze doc list at job creation
3. Use `is_soft_deleted` boolean on Documents
4. Workers process from snapshot, not live queries

---

## Implementation Plan

### 1. Database Changes (Migration 014)

**Matter table:**
```python
sync_status = Column(Enum(SyncStatus), default=SyncStatus.IDLE)  # IDLE, SYNCING, FAILED
```

**Document table:**
```python
is_soft_deleted = Column(Boolean, default=False, index=True)
```

**ProcessingJob table:**
```python
document_ids_snapshot = Column(JSON, nullable=True)  # Frozen list of doc IDs
```

---

### 2. Sync Flow with Locking

```
1. Check matter.sync_status == IDLE
   - If SYNCING: return error "Sync in progress"

2. Set matter.sync_status = SYNCING

3. Mark-and-Sweep:
   a. Get all doc IDs from Clio
   b. Soft-delete local docs NOT in Clio (is_soft_deleted = True)
   c. Upsert Clio docs (un-delete if previously soft-deleted)

4. Set matter.sync_status = IDLE
5. Update matter.last_synced_at
```

---

### 3. Process Flow with Snapshot

```
1. Check matter.sync_status == IDLE
   - If SYNCING: return error "Wait for sync to complete"

2. If matter.last_synced_at is NULL:
   - Run sync first (blocking)

3. Create ProcessingJob with:
   document_ids_snapshot = [list of doc IDs in selected folder where is_soft_deleted = False]

4. Return document count to frontend (for toast)

5. Workers read from document_ids_snapshot, NOT live query
   - If doc was soft-deleted mid-processing: skip gracefully
```

---

### 4. Sync Triggers (Only 3)

| Trigger | Condition | Action |
|---------|-----------|--------|
| First Login | User completes Clio OAuth | Sync all matters |
| Manual Sync | User clicks sync button | Sync selected matter |
| Process Click | `last_synced_at` is NULL | Sync matter, then process |

**Remove:** Auto-sync on matters page load

---

### 5. Frontend Changes

**Remove from `matters/page.tsx`:**
```tsx
// DELETE THIS useEffect
useEffect(() => {
  if (token && !hasAutoSynced) {
    setHasAutoSynced(true);
    api.syncAllDocuments(token).catch(console.error);
  }
}, [token, hasAutoSynced]);
```

**Add to `process/page.tsx`:**
- When folder selected → call API to get count → show toast
- Before processing → check if sync needed → show "Syncing..." state

---

### 6. New/Modified API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /matters/{id}/documents/count?folder_id=X` | Get doc count for toast |
| `POST /matters/{id}/sync` | Manual sync (with lock check) |
| `POST /jobs` | Creates job with `document_ids_snapshot` |

---

### 7. Handling Race Conditions

| Scenario | Solution |
|----------|----------|
| Process while syncing | Block with error: "Sync in progress" |
| Sync while processing | Allow - workers use snapshot, won't be affected |
| Doc deleted mid-process | Worker checks `is_soft_deleted`, skips if true |
| Count shown → docs changed | Snapshot freezes list at job creation time |

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/db/models.py` | Add `sync_status`, `is_soft_deleted`, `document_ids_snapshot` |
| `alembic/versions/014_...` | Migration for new columns |
| `app/worker/tasks.py` | Sync with lock + mark-sweep, process from snapshot |
| `app/api/v1/routes/matters.py` | Add count endpoint, sync with lock check |
| `app/api/v1/routes/jobs.py` | Create job with snapshot |
| `app/api/v1/routes/auth.py` | Trigger sync on first login |
| `frontend/.../matters/page.tsx` | Remove auto-sync |
| `frontend/.../process/page.tsx` | Add toast, sync-before-process check |
