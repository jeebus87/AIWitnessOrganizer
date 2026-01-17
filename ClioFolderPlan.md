# AIWitnessFinder: Document Organization Feature Implementation Plan

## Feature Overview

When the "Document Organization" toggle is enabled AND user clicks "Process" on a matter:
1. Create standardized folder tree in Clio (if not exists)
2. AI classifies each document during processing
3. Rename documents with format: `YYYY-MM-DD - [DocType] - [Description].ext`
4. Move documents to appropriate folders
5. Delete empty source folders
6. Update local database filename (for accurate exports)

---

## Phase 1: Database Schema Changes

### File: `app/db/models.py`

**Add to `User` model (per-user toggle):**
```python
enable_document_organizer = Column(Boolean, default=False, nullable=False)
```

**Add to `Document` model:**
```python
# Document organization tracking
is_organized = Column(Boolean, default=False, nullable=False, index=True)
organized_at = Column(DateTime, nullable=True)
organization_error = Column(Text, nullable=True)
original_filename = Column(String(512), nullable=True)  # Preserve original for audit trail
clio_folder_id = Column(String(128), nullable=True)  # Current folder in Clio
content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 for duplicate detection
```

### Migration:
Create Alembic migration for these new columns.

---

## Phase 2: Clio Client API Extensions

### File: `app/services/clio_client.py`

Add these new methods to `ClioClient` class:

```python
async def create_folder(
    self,
    matter_id: int,
    name: str,
    parent_id: Optional[int] = None
) -> Dict[str, Any]:
    """Create a folder in Clio"""
    data = {"data": {"name": name}}
    if parent_id:
        data["data"]["parent_id"] = parent_id

    response = await self._request(
        "POST",
        f"matters/{matter_id}/folders",
        json=data
    )
    return response.json().get("data", {})

async def update_document(
    self,
    document_id: int,
    name: Optional[str] = None,
    folder_id: Optional[int] = None
) -> Dict[str, Any]:
    """Update document name and/or move to folder"""
    data = {"data": {}}
    if name:
        data["data"]["name"] = name
    if folder_id:
        data["data"]["parent"] = {"id": folder_id}

    response = await self._request(
        "PATCH",
        f"documents/{document_id}",
        json=data
    )
    return response.json().get("data", {})

async def delete_folder(self, folder_id: int) -> bool:
    """Delete an empty folder"""
    await self._request("DELETE", f"folders/{folder_id}")
    return True

async def delete_document(self, document_id: int) -> bool:
    """Delete a document from Clio (use for duplicates)"""
    await self._request("DELETE", f"documents/{document_id}")
    return True

async def get_folder_contents(
    self,
    folder_id: int
) -> Dict[str, Any]:
    """Get documents and subfolders in a folder"""
    docs = []
    async for doc in self.get_documents_in_folder(folder_id):
        docs.append(doc)

    subfolders = []
    # Note: Need to check Clio API for subfolder listing

    return {"documents": docs, "subfolders": subfolders}
```

---

## Phase 3: Folder Structure Configuration

### New File: `app/core/folder_structure.py`

```python
"""Standard law firm folder structure for Clio matters"""

# Root-level folders (numeric prefix for sorting)
FOLDER_STRUCTURE = [
    "00_Case_Administration",
    "01_Correspondence",
    "02_Pleadings",
    "03_Discovery",
    "04_Depositions",
    "05_Legal_Research",
    "06_Work_Product",
    "07_Evidence",
    "08_Court_Orders",
    "09_Trial",
    "99_Final_Documents",
]

# Subfolder structure
SUBFOLDERS = {
    "00_Case_Administration": [
        "Engagement_Letters",
        "Billing_and_Invoices",
        "Conflict_Checks",
    ],
    "01_Correspondence": [
        "Client",
        "Opposing_Counsel",
        "Court",
        "Third_Parties",
    ],
    "02_Pleadings": [
        "Complaints",
        "Answers",
        "Motions",
        "Briefs",
        "Stipulations",
    ],
    "03_Discovery": [
        "Interrogatories",
        "Requests_for_Production",
        "Requests_for_Admission",
        "Document_Productions",
        "Subpoenas",
    ],
    "04_Depositions": [
        "Notices",
        "Transcripts",
        "Exhibits",
        "Video",
    ],
    "07_Evidence": [
        "Client_Documents",
        "Third_Party_Documents",
        "Expert_Reports",
        "Photos_and_Videos",
    ],
}

# Document type to folder mapping
DOC_TYPE_TO_FOLDER = {
    # Pleadings
    "complaint": "02_Pleadings/Complaints",
    "answer": "02_Pleadings/Answers",
    "motion": "02_Pleadings/Motions",
    "brief": "02_Pleadings/Briefs",
    "stipulation": "02_Pleadings/Stipulations",
    "pleading": "02_Pleadings",

    # Discovery
    "interrogatory": "03_Discovery/Interrogatories",
    "request_for_production": "03_Discovery/Requests_for_Production",
    "request_for_admission": "03_Discovery/Requests_for_Admission",
    "subpoena": "03_Discovery/Subpoenas",
    "discovery": "03_Discovery",

    # Depositions
    "deposition_notice": "04_Depositions/Notices",
    "deposition_transcript": "04_Depositions/Transcripts",
    "deposition": "04_Depositions",

    # Correspondence
    "letter": "01_Correspondence",
    "email": "01_Correspondence",
    "correspondence": "01_Correspondence",

    # Court Orders
    "order": "08_Court_Orders",
    "court_order": "08_Court_Orders",
    "judgment": "08_Court_Orders",

    # Evidence
    "evidence": "07_Evidence",
    "exhibit": "07_Evidence",
    "photo": "07_Evidence/Photos_and_Videos",
    "video": "07_Evidence/Photos_and_Videos",
    "expert_report": "07_Evidence/Expert_Reports",

    # Legal Research
    "legal_research": "05_Legal_Research",
    "memo": "05_Legal_Research",
    "case_law": "05_Legal_Research",

    # Admin
    "invoice": "00_Case_Administration/Billing_and_Invoices",
    "engagement": "00_Case_Administration/Engagement_Letters",
    "administrative": "00_Case_Administration",

    # Default
    "unknown": "00_Case_Administration",
}

# Document type abbreviations for filenames
DOC_TYPE_ABBREV = {
    "motion": "Mtn",
    "complaint": "Cmplt",
    "answer": "Ans",
    "brief": "Brf",
    "order": "Ord",
    "letter": "Ltr",
    "deposition_transcript": "Dep",
    "interrogatory": "ROG",
    "request_for_production": "RFP",
    "request_for_admission": "RFA",
    "subpoena": "Sub",
    "memo": "Memo",
    "invoice": "Inv",
    # Add more as needed
}
```

---

## Phase 4: AI Document Classification

### File: `app/services/bedrock_client.py`

Add new method for document classification:

```python
async def classify_document(
    self,
    text_content: str,
    filename: str
) -> Dict[str, Any]:
    """
    Classify a document and extract metadata for renaming.

    Returns:
        {
            "doc_type": "motion",
            "doc_date": "2026-01-15",  # or None if not found
            "description": "to Compel Discovery",
            "confidence": 0.95
        }
    """
    system_prompt = """You are an expert paralegal AI. Analyze the legal document and classify it.

Determine:
1. **Document Type**: Choose from: complaint, answer, motion, brief, stipulation, interrogatory, request_for_production, request_for_admission, subpoena, deposition_notice, deposition_transcript, letter, email, order, judgment, evidence, exhibit, expert_report, memo, invoice, engagement, photo, video, unknown
2. **Document Date**: Find the primary date (filing date, letter date, etc). Return YYYY-MM-DD format or null.
3. **Description**: 2-5 word description (e.g., "to Compel Discovery", "from Opposing Counsel re Settlement")

Return ONLY valid JSON:
{
    "doc_type": "motion",
    "doc_date": "2026-01-15",
    "description": "to Compel Discovery",
    "confidence": 0.95
}"""

    # Call Bedrock with document text
    # ... implementation using existing pattern
```

---

## Phase 4.5: Duplicate Detection Service

### Add to `app/services/document_processor.py`:

```python
import hashlib

def get_content_hash(self, content: bytes) -> str:
    """Generate SHA-256 hash of document content for duplicate detection"""
    return hashlib.sha256(content).hexdigest()
```

### Add to `DocumentOrganizer`:

```python
async def check_for_duplicates(
    self,
    document: Document,
    content_hash: str,
    session: AsyncSession
) -> Optional[Document]:
    """
    Check if this document is a duplicate of an already-organized document.

    Returns the original document if duplicate found, None otherwise.
    """
    # Look for documents with same hash that are already organized
    result = await session.execute(
        select(Document)
        .where(
            Document.content_hash == content_hash,
            Document.is_organized == True,
            Document.id != document.id,
            Document.matter_id == document.matter_id  # Same matter
        )
        .limit(1)
    )
    return result.scalar_one_or_none()

async def handle_duplicate(
    self,
    duplicate_doc: Document,
    original_doc: Document,
    clio_client: ClioClient,
    session: AsyncSession
) -> str:
    """
    Handle a duplicate document by DELETING it from Clio.

    Strategy: Delete duplicates to keep Clio clean.
    The original document remains, duplicate is removed.

    Returns: "deleted"
    """
    try:
        # Delete from Clio
        await clio_client.delete_document(int(duplicate_doc.clio_document_id))
        logger.info(f"Deleted duplicate document {duplicate_doc.clio_document_id} from Clio")

        # Remove from local database as well
        await session.delete(duplicate_doc)
        await session.commit()

        logger.info(
            f"Deleted duplicate document {duplicate_doc.id} "
            f"(was duplicate of {original_doc.id}: {original_doc.filename})"
        )
        return "deleted"

    except Exception as e:
        # If deletion fails, mark as error but don't crash
        duplicate_doc.organization_error = f"Failed to delete duplicate: {e}"
        await session.commit()
        logger.error(f"Failed to delete duplicate {duplicate_doc.id}: {e}")
        return "error"
```

### Duplicate Detection Flow:

```
For each document during processing:
1. Download content from Clio
2. Calculate SHA-256 hash
3. Store hash in Document.content_hash
4. Query for existing documents with same hash in ENTIRE MATTER
5. If duplicate found:
   - Skip AI classification (save credits)
   - DELETE document from Clio
   - DELETE document record from local database
   - Log deletion
   - Continue to next document
6. If not duplicate:
   - Proceed with normal classification and organization
```

### Important Safety Considerations:

1. **Deletion is permanent** - Clio API delete is not reversible
2. **Only delete if original exists and is organized** - Never delete the first copy
3. **Log all deletions** - Keep audit trail of what was removed
4. **Consider soft-delete option** - Could move to "Trash" folder instead if Clio supports

---

## Phase 5: Document Organization Service

### New File: `app/services/document_organizer.py`

```python
"""Service for organizing documents in Clio matters"""

class DocumentOrganizer:
    """Handles folder creation, document classification, renaming, and moving"""

    def __init__(self, clio_client: ClioClient, bedrock_client: BedrockClient):
        self.clio = clio_client
        self.bedrock = bedrock_client
        self.folder_cache: Dict[str, int] = {}  # path -> folder_id

    async def ensure_folder_structure(
        self,
        matter_id: int
    ) -> Dict[str, int]:
        """
        Create standard folder structure if not exists.
        Returns mapping of folder paths to Clio folder IDs.
        """
        # 1. Get existing folders
        existing = await self.clio.get_folder_tree(matter_id)
        existing_map = self._build_folder_map(existing)

        # 2. Create missing root folders
        for folder_name in FOLDER_STRUCTURE:
            if folder_name not in existing_map:
                result = await self.clio.create_folder(matter_id, folder_name)
                existing_map[folder_name] = result["id"]

        # 3. Create missing subfolders
        for parent, subfolders in SUBFOLDERS.items():
            parent_id = existing_map.get(parent)
            if parent_id:
                for subfolder in subfolders:
                    path = f"{parent}/{subfolder}"
                    if path not in existing_map:
                        result = await self.clio.create_folder(
                            matter_id, subfolder, parent_id=parent_id
                        )
                        existing_map[path] = result["id"]

        self.folder_cache = existing_map
        return existing_map

    async def classify_and_rename(
        self,
        document: Document,
        text_content: str
    ) -> Tuple[str, str, int]:
        """
        Classify document, generate new name, determine target folder.

        Returns: (new_filename, target_folder_path, target_folder_id)
        """
        # 1. AI classification
        classification = await self.bedrock.classify_document(
            text_content, document.filename
        )

        doc_type = classification["doc_type"]
        doc_date = classification["doc_date"]
        description = classification["description"]

        # 2. Build new filename
        abbrev = DOC_TYPE_ABBREV.get(doc_type, doc_type.title())
        ext = document.filename.rsplit(".", 1)[-1] if "." in document.filename else ""

        if doc_date:
            new_name = f"{doc_date} - {abbrev} - {description}.{ext}"
        else:
            new_name = f"{abbrev} - {description}.{ext}"

        # 3. Determine target folder
        folder_path = DOC_TYPE_TO_FOLDER.get(doc_type, "00_Case_Administration")
        folder_id = self.folder_cache.get(folder_path)

        # 4. Handle duplicates
        new_name = await self._ensure_unique_name(folder_id, new_name)

        return new_name, folder_path, folder_id

    async def _ensure_unique_name(
        self,
        folder_id: int,
        proposed_name: str
    ) -> str:
        """Append version suffix if name already exists in folder"""
        contents = await self.clio.get_folder_contents(folder_id)
        existing_names = {d["name"] for d in contents["documents"]}

        if proposed_name not in existing_names:
            return proposed_name

        # Add version suffix
        base, ext = proposed_name.rsplit(".", 1) if "." in proposed_name else (proposed_name, "")
        version = 2
        while True:
            versioned = f"{base}_v{version}.{ext}" if ext else f"{base}_v{version}"
            if versioned not in existing_names:
                return versioned
            version += 1

    async def organize_document(
        self,
        document: Document,
        text_content: str,
        session: AsyncSession
    ) -> bool:
        """
        Full organization flow for a single document.
        Returns True on success.
        """
        try:
            # 1. Classify and get new name
            new_name, folder_path, folder_id = await self.classify_and_rename(
                document, text_content
            )

            # 2. Store original filename (first time only)
            if not document.original_filename:
                document.original_filename = document.filename

            # 3. Update in Clio (rename + move)
            await self.clio.update_document(
                int(document.clio_document_id),
                name=new_name,
                folder_id=folder_id
            )

            # 4. Update local database
            document.filename = new_name  # THIS updates exports!
            document.clio_folder_id = str(folder_id)
            document.is_organized = True
            document.organized_at = datetime.utcnow()
            document.organization_error = None

            await session.commit()
            return True

        except Exception as e:
            document.organization_error = str(e)
            await session.commit()
            return False
```

---

## Phase 6: Integration with Processing Pipeline

### File: `app/worker/tasks.py`

Modify `_process_single_document_async` to include organization step:

```python
async def _process_single_document_async(
    task,
    document_id: int,
    search_targets: Optional[List[str]] = None,
    organize_documents: bool = False  # NEW PARAMETER
):
    # ... existing code for witness extraction ...

    # NEW: Document organization step (after successful processing)
    if organize_documents and extraction_result.success:
        try:
            organizer = DocumentOrganizer(clio, bedrock)

            # Get text content for classification
            text_content = await processor.extract_text(content, document.filename)

            # Organize the document
            success = await organizer.organize_document(
                document, text_content, session
            )

            if success:
                logger.info(f"Document {document_id} organized: {document.filename}")
            else:
                logger.warning(f"Document {document_id} organization failed: {document.organization_error}")

        except Exception as e:
            logger.error(f"Organization error for document {document_id}: {e}")
            document.organization_error = str(e)
            await session.commit()
```

Modify `_process_matter_async`:

```python
async def _process_matter_async(
    task, job_id: int, matter_id: int,
    search_targets: Optional[List[str]] = None,
    scan_folder_id: Optional[int] = None,
    legal_authority_folder_id: Optional[int] = None,
    include_subfolders: bool = True,
    organize_documents: bool = False  # NEW PARAMETER
):
    # ... existing setup code ...

    # NEW: Check organization setting and create folder structure
    if organize_documents:
        # Get organization setting
        result = await session.execute(
            select(Organization)
            .join(User)
            .where(User.id == matter.user_id)
        )
        org = result.scalar_one_or_none()

        if org and org.enable_document_organizer:
            organizer = DocumentOrganizer(clio, bedrock)
            await organizer.ensure_folder_structure(int(matter.clio_matter_id))
            logger.info(f"Created/verified folder structure for matter {matter_id}")

    # ... existing document processing loop ...
    # Pass organize_documents flag to _process_single_document_async
```

---

## Phase 7: API Endpoint Updates

### File: `app/api/v1/routes/matters.py`

Update `ProcessMatterRequest` schema:

```python
class ProcessMatterRequest(BaseModel):
    scan_folder_id: Optional[int] = None
    legal_authority_folder_id: Optional[int] = None
    include_subfolders: bool = True
    organize_documents: bool = False  # NEW - uses org setting if True
```

---

## Phase 8: Frontend Toggle

### File: `frontend/src/app/(authenticated)/settings/page.tsx`

Add toggle to organization settings:

```tsx
<div className="flex items-center justify-between">
  <div>
    <h4 className="font-medium">Document Organization</h4>
    <p className="text-sm text-muted-foreground">
      Automatically organize and rename documents during processing
    </p>
  </div>
  <Switch
    checked={settings.enable_document_organizer}
    onCheckedChange={(checked) => updateSetting('enable_document_organizer', checked)}
  />
</div>
```

### File: `frontend/src/components/matters/folder-selection-dialog.tsx`

Show organization option when enabled:

```tsx
{organizationSettings?.enable_document_organizer && (
  <div className="flex items-center gap-2 p-3 bg-blue-50 rounded-md">
    <Checkbox
      checked={organizeDocuments}
      onCheckedChange={setOrganizeDocuments}
    />
    <span className="text-sm">
      Organize documents into standard folder structure
    </span>
  </div>
)}
```

---

## Phase 9: Empty Folder Cleanup

### Add to `DocumentOrganizer`:

```python
async def cleanup_empty_folders(
    self,
    matter_id: int,
    source_folder_ids: List[int]
) -> int:
    """
    Delete empty source folders after moving documents.
    Returns count of deleted folders.
    """
    deleted = 0
    for folder_id in source_folder_ids:
        try:
            contents = await self.clio.get_folder_contents(folder_id)
            if not contents["documents"] and not contents["subfolders"]:
                await self.clio.delete_folder(folder_id)
                deleted += 1
                logger.info(f"Deleted empty folder {folder_id}")
        except Exception as e:
            logger.warning(f"Could not delete folder {folder_id}: {e}")
    return deleted
```

---

## Export Integration (Automatic)

The export feature already uses `document.filename` via:
- `app/services/export_service.py:72-78` (`_format_source_document`)
- `app/api/v1/routes/witnesses.py:242` (returns `w.document.filename`)

Since we update `Document.filename` in the database after renaming in Clio, exports will **automatically reflect the new names** with no additional changes required.

---

## Critical Files to Modify

| File | Changes |
|------|---------|
| `app/db/models.py` | Add `enable_document_organizer`, `document_storage` to User; add `is_organized`, `organized_at`, `organization_error`, `original_filename`, `clio_folder_id`, `content_hash` to Document; add `DropboxIntegration` model |
| `app/services/clio_client.py` | Add create_folder, update_document, delete_folder, delete_document |
| `app/services/dropbox_client.py` | NEW - Dropbox API client with OAuth |
| `app/services/storage_interface.py` | NEW - Abstract interface + Clio/Dropbox adapters |
| `app/services/bedrock_client.py` | Add classify_document method |
| `app/services/document_organizer.py` | NEW - main organization logic (uses storage interface) |
| `app/core/folder_structure.py` | NEW - folder config and mappings |
| `app/worker/tasks.py` | Integrate organization into processing |
| `app/api/v1/routes/matters.py` | Add organize_documents param |
| `app/api/v1/routes/auth.py` | Add Dropbox OAuth endpoints |
| `frontend/src/app/.../settings/page.tsx` | Add toggle UI + storage selection |
| `frontend/src/components/.../folder-selection-dialog.tsx` | Add organize option |

---

## Order of Operations (Processing Flow)

```
1. User enables toggle in Settings (User.enable_document_organizer = True)
   - This is a PER-USER setting

2. User clicks "Process" on a matter with organize option checked

3. Backend receives request with organize_documents=True

4. Celery task starts:
   a. Check User.enable_document_organizer
   b. If enabled: ensure_folder_structure() - create folders idempotently
   c. For each document:
      i.    Download from Clio
      ii.   Calculate SHA-256 content hash
      iii.  Check for duplicates (same hash in matter)
      iv.   IF DUPLICATE (same hash exists in matter):
            - Skip AI processing (save credits)
            - DELETE document from Clio
            - DELETE document from local database
            - Log deletion with reference to original
            - Continue to next document
      v.    Extract text content
      vi.   AI witness extraction (existing)
      vii.  AI document classification (NEW)
      viii. Generate new filename:
            - With date: "2026-01-15 - Mtn - to Compel.pdf"
            - Without date (if not found): "Mtn - to Compel.pdf"
      ix.   Check for name duplicates in target folder (add _v2, _v3)
      x.    Store original_filename for audit trail
      xi.   Update in Clio (rename + move)
      xii.  Update Document.filename in DB (for exports)
      xiii. Mark is_organized = True
   d. Cleanup empty source folders

5. Export reports show new filenames automatically
```

---

## Error Handling Strategy

1. **Folder creation fails**: Retry task, idempotent operation will resume
2. **Document classification fails**: Log error, skip organization, continue processing
3. **Clio rename/move fails**: Log to `Document.organization_error`, mark as not organized
4. **Rate limiting**: Existing RateLimiter handles with exponential backoff
5. **Duplicate names**: Automatic versioning (_v2, _v3, etc.)
6. **Duplicate deletion fails**: Log error in `organization_error`, keep document, continue
7. **Clio API errors (401, 403)**: Refresh token, retry; if still fails, abort task

---

## Verification/Testing

1. **Unit tests**: Test folder structure creation, document classification, naming logic
2. **Integration tests**:
   - Create test matter in Clio sandbox
   - Upload sample documents
   - Run processing with organization enabled
   - Verify folder structure created
   - Verify documents renamed and moved
   - Verify exports show new names
3. **Manual testing**:
   - Enable toggle in settings
   - Process a matter with mixed document types
   - Check Clio for correct folder structure
   - Check document names match expected format
   - Export PDF/Excel and verify source document column

---

## Phase 10: Dropbox Integration (Alternative Storage)

For users who use Dropbox instead of Clio's document storage, provide the same folder structure and naming capabilities.

### Research Required:

1. **Dropbox API Investigation**
   - Dropbox API v2: https://www.dropbox.com/developers/documentation/http/documentation
   - OAuth 2.0 flow (similar to Clio)
   - Rate limits and quotas

2. **Key Dropbox API Endpoints**
   ```
   POST /files/create_folder_v2        - Create folder
   POST /files/move_v2                 - Move/rename file
   POST /files/delete_v2               - Delete file/folder
   POST /files/list_folder             - List folder contents
   POST /files/download                - Download file content
   POST /files/get_metadata            - Get file metadata
   ```

### New File: `app/services/dropbox_client.py`

```python
"""Dropbox API client with OAuth and rate limiting"""

class DropboxClient:
    """
    Async client for Dropbox API v2 with OAuth 2.0.
    Mirrors ClioClient interface for consistency.
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
        on_token_refresh: Optional[callable] = None
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at
        self.on_token_refresh = on_token_refresh
        self.base_url = "https://api.dropboxapi.com/2"
        self.content_url = "https://content.dropboxapi.com/2"

    async def create_folder(self, path: str) -> Dict[str, Any]:
        """Create a folder at the specified path"""
        # POST /files/create_folder_v2
        pass

    async def move_file(
        self,
        from_path: str,
        to_path: str
    ) -> Dict[str, Any]:
        """Move/rename a file"""
        # POST /files/move_v2
        pass

    async def delete_file(self, path: str) -> bool:
        """Delete a file or folder"""
        # POST /files/delete_v2
        pass

    async def list_folder(
        self,
        path: str,
        recursive: bool = False
    ) -> List[Dict[str, Any]]:
        """List contents of a folder"""
        # POST /files/list_folder
        pass

    async def download_file(self, path: str) -> bytes:
        """Download file content"""
        # POST /files/download (content endpoint)
        pass

    async def get_file_metadata(self, path: str) -> Dict[str, Any]:
        """Get file metadata including content_hash"""
        # POST /files/get_metadata
        pass
```

### Database Schema Additions

**Add to `User` model:**
```python
# Storage preference
document_storage = Column(String(20), default="clio", nullable=False)  # "clio" or "dropbox"
```

**Add to `ClioIntegration` or new `DropboxIntegration` model:**
```python
class DropboxIntegration(Base):
    """Dropbox OAuth integration for a user"""
    __tablename__ = "dropbox_integrations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)

    dropbox_account_id = Column(String(128), nullable=True)
    root_folder_path = Column(String(512), nullable=True)  # e.g., "/Law Firm/Matters"

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### Dropbox Folder Structure

Same structure as Clio, but using Dropbox paths:

```
/Law Firm/Matters/
└── [Client Name]/
    └── [Matter Name]/
        ├── 00_Case_Administration/
        ├── 01_Correspondence/
        ├── 02_Pleadings/
        │   ├── Complaints/
        │   ├── Answers/
        │   ├── Motions/
        │   └── ...
        ├── 03_Discovery/
        └── ... (same structure as Clio)
```

### Storage Abstraction Layer

Create a unified interface for both Clio and Dropbox:

```python
# app/services/storage_interface.py

from abc import ABC, abstractmethod

class DocumentStorageInterface(ABC):
    """Abstract interface for document storage providers"""

    @abstractmethod
    async def create_folder(self, path: str, parent_id: Optional[str] = None) -> str:
        """Create folder, return folder ID/path"""
        pass

    @abstractmethod
    async def move_document(self, doc_id: str, new_name: str, folder_id: str) -> bool:
        """Move and rename document"""
        pass

    @abstractmethod
    async def delete_document(self, doc_id: str) -> bool:
        """Delete document"""
        pass

    @abstractmethod
    async def delete_folder(self, folder_id: str) -> bool:
        """Delete empty folder"""
        pass

    @abstractmethod
    async def get_folder_contents(self, folder_id: str) -> Dict[str, Any]:
        """Get documents and subfolders"""
        pass

    @abstractmethod
    async def download_document(self, doc_id: str) -> bytes:
        """Download document content"""
        pass


class ClioStorageAdapter(DocumentStorageInterface):
    """Clio implementation of storage interface"""
    def __init__(self, clio_client: ClioClient):
        self.client = clio_client
    # ... implement methods using ClioClient


class DropboxStorageAdapter(DocumentStorageInterface):
    """Dropbox implementation of storage interface"""
    def __init__(self, dropbox_client: DropboxClient):
        self.client = dropbox_client
    # ... implement methods using DropboxClient
```

### Modified DocumentOrganizer

```python
class DocumentOrganizer:
    def __init__(
        self,
        storage: DocumentStorageInterface,  # Now accepts either Clio or Dropbox
        bedrock_client: BedrockClient
    ):
        self.storage = storage
        self.bedrock = bedrock_client
```

### Frontend: Storage Selection

**Settings page addition:**
```tsx
<div className="space-y-4">
  <h4 className="font-medium">Document Storage</h4>
  <RadioGroup
    value={settings.document_storage}
    onValueChange={(v) => updateSetting('document_storage', v)}
  >
    <div className="flex items-center space-x-2">
      <RadioGroupItem value="clio" id="clio" />
      <Label htmlFor="clio">Clio Document Storage</Label>
    </div>
    <div className="flex items-center space-x-2">
      <RadioGroupItem value="dropbox" id="dropbox" />
      <Label htmlFor="dropbox">Dropbox</Label>
      {!hasDropboxIntegration && (
        <Button variant="outline" size="sm" onClick={connectDropbox}>
          Connect Dropbox
        </Button>
      )}
    </div>
  </RadioGroup>
</div>
```

### OAuth Routes for Dropbox

**Add to `app/api/v1/routes/auth.py`:**
```python
@router.get("/dropbox")
async def dropbox_login():
    """Initiate Dropbox OAuth flow"""
    # Similar to Clio OAuth
    pass

@router.get("/dropbox/callback")
async def dropbox_callback(code: str, state: str):
    """Handle Dropbox OAuth callback"""
    pass
```

### Dropbox-Specific Considerations

1. **Path-based vs ID-based**
   - Clio uses document IDs
   - Dropbox uses file paths (can also use file IDs)
   - Need to handle both in storage abstraction

2. **Content Hash**
   - Dropbox provides `content_hash` in metadata (no need to calculate)
   - Can use directly for duplicate detection

3. **Rate Limits**
   - Dropbox: ~1000 calls per user per hour for most endpoints
   - Less restrictive than Clio, but still need rate limiting

4. **Shared Folders**
   - Consider if law firm uses shared team folders
   - May need team-level OAuth scope

### Implementation Priority

1. **Phase 10a**: Research Dropbox API, confirm endpoints work as expected
2. **Phase 10b**: Create DropboxClient with OAuth
3. **Phase 10c**: Create storage abstraction layer
4. **Phase 10d**: Refactor DocumentOrganizer to use abstraction
5. **Phase 10e**: Add frontend storage selection
6. **Phase 10f**: Testing with both Clio and Dropbox
