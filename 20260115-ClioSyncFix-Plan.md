# Clio Sync Fix Plan

## Problem

Clio sync is not returning matter data because **the `fields` parameter is not being passed** to the Clio API.

### Root Cause (confirmed by Gemini)

When calling `GET /api/v4/matters` without a `fields` parameter, Clio API v4 returns **only `id` and `etag`** by default. Our code expects `display_number`, `description`, `status`, and `client.name`, but these fields are never requested.

### Current Code (broken)

```python
# clio_client.py
async def get_matters(self, status: Optional[str] = "Open", fields: Optional[List[str]] = None):
    params = {}
    if status:
        params["status"] = status
    if fields:
        params["fields"] = ",".join(fields)  # Fields never passed!
    async for matter in self.get_paginated("matters", params):
        yield matter

# matters.py (caller)
async for matter_data in clio.get_matters(status=status):
    # Tries to access fields that were never requested!
    matter_data.get("display_number")  # Returns None
    matter_data.get("client", {}).get("name")  # Returns None
```

---

## Solution

### Step 1: Add Default Fields to `get_matters`

**File:** `app/services/clio_client.py`

Change the `get_matters` method to have sensible default fields:

```python
# Default fields that are commonly needed for matters
DEFAULT_MATTER_FIELDS = [
    "id",
    "display_number",
    "description",
    "status",
    "practice_area",
    "client{name}",  # Nested field syntax for Clio API
]

async def get_matters(
    self,
    status: Optional[str] = "Open",
    fields: Optional[List[str]] = None
) -> AsyncIterator[Dict[str, Any]]:
    """Get all matters (paginated). Pass status=None to get ALL matters."""
    # Use default fields if none specified
    if fields is None:
        fields = DEFAULT_MATTER_FIELDS

    params = {}
    if status:
        params["status"] = status
    if fields:
        params["fields"] = ",".join(fields)

    async for matter in self.get_paginated("matters", params):
        yield matter
```

### Step 2: No Changes Needed to Caller

The `matters.py` sync function can remain unchanged because:
- It already calls `clio.get_matters(status=status)`
- The default fields will now be automatically included
- The existing field access code will work: `matter_data.get("display_number")`, etc.

---

## Why This Fix Works (Gemini's Explanation)

1. **Clio API v4 requires explicit field requests** - Unlike some APIs that return all fields by default, Clio returns minimal data unless you specify what you want.

2. **Nested field syntax `client{name}`** - This is the correct Clio API format for requesting fields from related objects.

3. **Default fields in the client** - Encapsulating commonly-needed fields as defaults makes the API client robust and prevents this issue from recurring.

---

## Files to Modify

| File | Change |
|------|--------|
| `app/services/clio_client.py` | Add `DEFAULT_MATTER_FIELDS` constant and update `get_matters` to use it |

---

## Testing Checklist

1. [ ] Call sync endpoint with `include_archived=False` - should return Open matters with all fields
2. [ ] Call sync endpoint with `include_archived=True` - should return ALL matters with all fields
3. [ ] Verify `display_number` is populated in synced matters
4. [ ] Verify `client_name` is populated in synced matters
5. [ ] Verify `description` is populated in synced matters
6. [ ] Check database after sync to confirm data is saved
