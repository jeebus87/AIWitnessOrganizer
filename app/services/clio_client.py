"""Clio API client with OAuth and rate limiting"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, AsyncIterator, List
from urllib.parse import urlencode, urlparse, parse_qs, urlunsplit

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.core.security import encrypt_token, decrypt_token


class RateLimiter:
    """Token bucket rate limiter for Clio API (50 requests/minute)"""

    def __init__(self, capacity: int = 50, refill_rate: float = 50 / 60):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)  # tokens per second
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until tokens are available, then consume them"""
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                # Calculate wait time
                wait_time = (tokens - self.tokens) / self.refill_rate
                await asyncio.sleep(min(wait_time, 0.1))

    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now


class ClioRateLimitError(Exception):
    """Raised when Clio rate limit is hit"""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


class ClioAuthError(Exception):
    """Raised when Clio authentication fails"""
    pass


class ClioClient:
    """
    Async client for Clio API v4 with OAuth 2.0 and rate limiting.

    Usage:
        client = ClioClient(access_token="...", refresh_token="...")
        async for matter in client.get_all_matters():
            print(matter)
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
        region: str = "us",
        on_token_refresh: Optional[callable] = None
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at
        self.region = region
        self.on_token_refresh = on_token_refresh  # Callback to save refreshed tokens

        # Set base URL based on region
        if region == "eu":
            self.base_url = "https://eu.app.clio.com"
        else:
            self.base_url = "https://app.clio.com"

        self.api_url = f"{self.base_url}/api/v4"
        self.rate_limiter = RateLimiter()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with ClioClient(...) as client:'")
        return self._client

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with current access token"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _ensure_valid_token(self) -> None:
        """Refresh token if expired or about to expire (within 5 minutes)"""
        buffer = timedelta(minutes=5)
        if datetime.utcnow() + buffer >= self.token_expires_at:
            await self._refresh_access_token()

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token"""
        token_url = f"{self.base_url}/oauth/token"

        data = {
            "grant_type": "refresh_token",
            "client_id": settings.clio_client_id,
            "client_secret": settings.clio_client_secret,
            "refresh_token": self.refresh_token,
        }

        response = await self.client.post(token_url, data=data)

        if response.status_code != 200:
            raise ClioAuthError(f"Failed to refresh token: {response.text}")

        token_data = response.json()
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]
        self.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])

        # Call the callback to persist the new tokens
        if self.on_token_refresh:
            await self.on_token_refresh(
                access_token=self.access_token,
                refresh_token=self.refresh_token,
                expires_at=self.token_expires_at
            )

    @retry(
        retry=retry_if_exception_type(ClioRateLimitError),
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=2, max=120),
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> httpx.Response:
        """Make a rate-limited request to Clio API"""
        await self._ensure_valid_token()
        await self.rate_limiter.acquire()

        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"{self.api_url}/{endpoint.lstrip('/')}"

        response = await self.client.request(
            method,
            url,
            headers=self._get_headers(),
            **kwargs
        )

        # Handle rate limiting
        if response.status_code == 429:
            retry_after = int(response.headers.get("X-RateLimit-Reset", 60))
            raise ClioRateLimitError(retry_after)

        # Handle auth errors
        if response.status_code == 401:
            # Try to refresh token and retry
            await self._refresh_access_token()
            response = await self.client.request(
                method,
                url,
                headers=self._get_headers(),
                **kwargs
            )
            if response.status_code == 401:
                raise ClioAuthError("Authentication failed after token refresh")

        response.raise_for_status()
        return response

    async def get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """GET request to Clio API"""
        response = await self._request("GET", endpoint, **kwargs)
        return response.json()

    async def get_paginated(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        page_size: int = 200
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Iterate through paginated Clio API results using cursor-based pagination.
        Yields individual items from the 'data' array.

        Uses cursor pagination with order=id(asc) to bypass the 10,000 offset limit.
        The API returns a meta.paging.next URL to fetch the next page.
        """
        params = params or {}
        params["limit"] = page_size
        params["order"] = "id(asc)"  # Required for cursor-based pagination
        # Don't use offset - cursor pagination handles this via the next URL

        seen_ids: set = set()  # Track seen IDs to detect duplicates
        next_url: Optional[str] = None
        is_first_request = True

        while True:
            if is_first_request:
                response = await self.get(endpoint, params=params)
                is_first_request = False
            else:
                # Use the next URL directly (it includes cursor parameter)
                response = await self.get(next_url)

            data = response.get("data", [])

            if not data:
                break

            # Yield items, checking for duplicates
            for item in data:
                item_id = item.get("id")
                if item_id in seen_ids:
                    return  # Stop iteration if we see duplicates
                seen_ids.add(item_id)
                yield item

            # Check for next page URL in cursor pagination
            meta = response.get("meta", {})
            paging = meta.get("paging", {})
            next_url = paging.get("next")

            if not next_url:
                break  # No more pages

    # =========================================================================
    # Matter Operations
    # =========================================================================

    # Default fields needed for matters - Clio API returns only id/etag without explicit fields
    # Note: status, practice_area, and client are nested objects that return {id, name, ...}
    # We request the full objects (not {name} suffix) so extract_nested can handle them properly
    DEFAULT_MATTER_FIELDS = [
        "id",
        "display_number",
        "description",
        "status",        # Nested object: returns {"status": {"id": 1, "name": "Open"}}
        "practice_area", # Nested object: returns {"practice_area": {"id": 1, "name": "Litigation"}}
        "client",        # Nested object: returns {"client": {"id": 1, "name": "John Doe"}}
    ]

    async def get_matters(
        self,
        status: Optional[str] = "Open",
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Get all matters (paginated). Pass status=None to get ALL matters."""
        # Use default fields if none specified - Clio returns only id/etag otherwise!
        if fields is None:
            fields = self.DEFAULT_MATTER_FIELDS

        params = {}
        if status:  # Only add status if provided (None = get all)
            params["status"] = status
        if fields:
            params["fields"] = ",".join(fields)
        async for matter in self.get_paginated("matters", params):
            yield matter

    async def get_matter(self, matter_id: int) -> Dict[str, Any]:
        """Get a single matter by ID"""
        response = await self.get(f"matters/{matter_id}")
        return response.get("data", {})

    # =========================================================================
    # Document Operations
    # =========================================================================

    # Default fields needed for documents - Clio API returns only id/etag without explicit fields
    DEFAULT_DOCUMENT_FIELDS = [
        "id",
        "name",
        "content_type",
        "size",
        "etag",
        "created_at",
        "updated_at",
    ]

    async def get_documents(
        self,
        matter_id: Optional[int] = None,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Get all documents, optionally filtered by matter"""
        # Use default fields if none specified - Clio returns only id/etag otherwise!
        if fields is None:
            fields = self.DEFAULT_DOCUMENT_FIELDS

        params = {}
        if matter_id:
            params["matter_id"] = matter_id
        if fields:
            params["fields"] = ",".join(fields)
        async for doc in self.get_paginated("documents", params):
            yield doc

    async def get_document(self, document_id: int) -> Dict[str, Any]:
        """Get a single document by ID"""
        # Request default fields to ensure we get name, content_type, etc.
        params = {"fields": ",".join(self.DEFAULT_DOCUMENT_FIELDS)}
        response = await self.get(f"documents/{document_id}", params=params)
        return response.get("data", {})

    async def download_document(self, document_id: int) -> bytes:
        """
        Download document content.
        Handles the 303 redirect to pre-signed S3 URL.
        """
        await self._ensure_valid_token()
        await self.rate_limiter.acquire()

        url = f"{self.api_url}/documents/{document_id}/download"

        # Make initial request with follow_redirects=True
        response = await self.client.get(
            url,
            headers=self._get_headers(),
            follow_redirects=True
        )
        response.raise_for_status()

        return response.content

    # =========================================================================
    # Folder Operations
    # =========================================================================

    DEFAULT_FOLDER_FIELDS = [
        "id",
        "name",
        "parent",
        "created_at",
        "updated_at",
    ]

    async def get_folders(
        self,
        matter_id: int,
        parent_id: Optional[int] = None,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Get folders for a matter.

        Args:
            matter_id: The matter ID to get folders for
            parent_id: Optional parent folder ID to get subfolders
            fields: Fields to return
        """
        if fields is None:
            fields = self.DEFAULT_FOLDER_FIELDS

        params = {"matter_id": matter_id}
        if parent_id:
            params["parent_id"] = parent_id
        if fields:
            params["fields"] = ",".join(fields)

        async for folder in self.get_paginated("folders", params):
            yield folder

    async def get_folder(self, folder_id: int) -> Dict[str, Any]:
        """Get a single folder by ID"""
        params = {"fields": ",".join(self.DEFAULT_FOLDER_FIELDS)}
        response = await self.get(f"folders/{folder_id}", params=params)
        return response.get("data", {})

    async def get_folder_tree(self, matter_id: int) -> List[Dict[str, Any]]:
        """
        Get the complete folder tree for a matter.
        Returns a nested structure with children.
        """
        # Get all folders for the matter
        all_folders = []
        async for folder in self.get_folders(matter_id):
            all_folders.append(folder)

        # Build tree structure
        folder_map = {f["id"]: {**f, "children": []} for f in all_folders}
        root_folders = []

        for folder in all_folders:
            parent = folder.get("parent")
            if parent and parent.get("id") in folder_map:
                folder_map[parent["id"]]["children"].append(folder_map[folder["id"]])
            else:
                root_folders.append(folder_map[folder["id"]])

        return root_folders

    async def get_documents_in_folder(
        self,
        folder_id: int,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Get documents in a specific folder"""
        if fields is None:
            fields = self.DEFAULT_DOCUMENT_FIELDS

        params = {
            "folder_id": folder_id,
            "fields": ",".join(fields)
        }

        async for doc in self.get_paginated("documents", params):
            yield doc

    async def get_documents_recursive(
        self,
        matter_id: int,
        folder_id: int,
        exclude_folder_ids: Optional[List[int]] = None,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Recursively get all documents in a folder and its subfolders.

        Args:
            matter_id: The matter ID
            folder_id: The root folder ID to start from
            exclude_folder_ids: List of folder IDs to exclude (e.g., Legal Authority folder)
            fields: Document fields to return
        """
        if exclude_folder_ids is None:
            exclude_folder_ids = []

        if fields is None:
            fields = self.DEFAULT_DOCUMENT_FIELDS

        # Get documents in the current folder
        async for doc in self.get_documents_in_folder(folder_id, fields):
            yield doc

        # Get subfolders and recurse
        async for subfolder in self.get_folders(matter_id, parent_id=folder_id):
            subfolder_id = subfolder.get("id")
            if subfolder_id and subfolder_id not in exclude_folder_ids:
                async for doc in self.get_documents_recursive(
                    matter_id, subfolder_id, exclude_folder_ids, fields
                ):
                    yield doc

    async def get_all_matter_documents_via_folders(
        self,
        matter_id: int,
        exclude_folder_ids: Optional[List[int]] = None,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Get ALL documents in a matter using cursor-based pagination.

        Now that get_paginated uses cursor pagination with order=id(asc),
        this method simply fetches all documents for the matter directly.
        Cursor pagination bypasses the 10,000 offset limit.

        Args:
            matter_id: The Clio matter ID (not database ID)
            exclude_folder_ids: List of folder IDs to exclude (not used with direct query)
            fields: Document fields to return
        """
        if fields is None:
            fields = self.DEFAULT_DOCUMENT_FIELDS

        # With cursor-based pagination, we can fetch all documents directly
        # The get_paginated method now uses order=id(asc) which enables cursor pagination
        async for doc in self.get_documents(matter_id=matter_id, fields=fields):
            yield doc

    # =========================================================================
    # Contact Operations
    # =========================================================================

    async def get_contacts(
        self,
        type: Optional[str] = None,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Get all contacts"""
        params = {}
        if type:
            params["type"] = type
        if fields:
            params["fields"] = ",".join(fields)
        async for contact in self.get_paginated("contacts", params):
            yield contact


def get_clio_authorize_url(state: str, redirect_uri: Optional[str] = None) -> str:
    """Generate the Clio OAuth authorization URL"""
    params = {
        "response_type": "code",
        "client_id": settings.clio_client_id,
        "redirect_uri": redirect_uri or settings.clio_redirect_uri,
        "state": state,
    }
    return f"{settings.clio_authorize_url}?{urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: Optional[str] = None
) -> Dict[str, Any]:
    """Exchange authorization code for access and refresh tokens"""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.clio_client_id,
        "client_secret": settings.clio_client_secret,
        "redirect_uri": redirect_uri or settings.clio_redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(settings.clio_token_url, data=data)
        response.raise_for_status()
        return response.json()


async def get_clio_user_info(access_token: str, include_firm: bool = False) -> Dict[str, Any]:
    """
    Get the current Clio user's information.
    Uses the /users/who_am_i endpoint.

    Args:
        access_token: The Clio access token
        include_firm: If True, include firm/account information in the response
    """
    fields = ["id", "email", "name", "first_name", "last_name"]
    if include_firm:
        fields.extend(["account"])  # Account contains firm info

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.clio_api_url}/users/who_am_i",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={"fields": ",".join(fields)}
        )
        response.raise_for_status()
        return response.json().get("data", {})


async def get_clio_account_info(access_token: str) -> Dict[str, Any]:
    """
    Get the Clio account/firm information.
    Returns firm name, address, phone, etc.
    """
    fields = ["id", "name", "maildrop_address", "phone_number"]

    async with httpx.AsyncClient() as client:
        # Get account info from the who_am_i endpoint with account fields
        response = await client.get(
            f"{settings.clio_api_url}/users/who_am_i",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={"fields": "account{id,name}"}
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        return data.get("account", {})


async def verify_clio_admin_permission(access_token: str) -> bool:
    """
    Check Clio API in real-time for admin/billing permission status.

    CRITICAL: This check is performed BEFORE every billing operation.
    Do NOT cache this result - permissions can change at any time.

    Returns True if user is account owner or has billing management rights.
    """
    async with httpx.AsyncClient() as client:
        # Request user info with account_owner and subscription fields
        response = await client.get(
            f"{settings.clio_api_url}/users/who_am_i",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={"fields": "id,account_owner,subscription_type,enabled"}
        )

        if response.status_code != 200:
            # If we can't verify, deny access for safety
            return False

        data = response.json().get("data", {})

        # Check if user is account owner (has billing rights)
        is_account_owner = data.get("account_owner", False)

        # In Clio, account_owner is the primary indicator of billing rights
        # Users who are account owners can manage subscriptions and billing
        return is_account_owner


async def get_clio_user_count(access_token: str) -> int:
    """
    Get the count of enabled users in the Clio account.
    Used for calculating subscription billing.
    """
    count = 0
    async with httpx.AsyncClient() as client:
        # Get all users with pagination
        offset = 0
        page_size = 200

        while True:
            response = await client.get(
                f"{settings.clio_api_url}/users",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                params={
                    "fields": "id,enabled",
                    "limit": page_size,
                    "offset": offset
                }
            )

            if response.status_code != 200:
                break

            data = response.json().get("data", [])
            if not data:
                break

            # Count only enabled users
            count += sum(1 for user in data if user.get("enabled", True))

            if len(data) < page_size:
                break

            offset += page_size

    return count
