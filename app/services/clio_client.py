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
        before_sleep=lambda retry_state: print(f"DEBUG: Rate limit hit. Retrying attempt {retry_state.attempt_number}...")
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

        # Debug logging
        print(f"DEBUG: _request endpoint='{endpoint}' startswith_http={endpoint.startswith('http')}")

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
        params: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Iterate through paginated Clio API results.
        Yields individual items from the 'data' array.
        """
        params = params or {}
        url = endpoint
        # Preserve fields param - Clio's "next" URL doesn't always include it
        fields_param = params.get("fields")
        prev_url = None  # Track previous URL to detect infinite loops

        while url:
            # Detect infinite loop - same URL being requested twice
            if url == prev_url:
                print(f"WARNING: Pagination loop detected, same URL returned twice: {url[:100]}...")
                break
            prev_url = url

            # If this is a full URL (pagination), ensure fields param is included
            if url.startswith("http") and fields_param:
                parsed = urlparse(url)
                query_params = parse_qs(parsed.query)
                if "fields" not in query_params:
                    # Add fields to the URL directly
                    separator = "&" if parsed.query else "?"
                    url = f"{url}{separator}fields={fields_param}"
                    print(f"DEBUG: Added fields to pagination URL")

            response = await self.get(url, params={} if url.startswith("http") else params)
            data = response.get("data", [])

            # Debug: log data count and paging info
            paging = response.get("meta", {}).get("paging", {})
            print(f"DEBUG: Page returned {len(data)} items, paging: {paging}")

            for item in data:
                yield item

            # If no data returned, stop pagination (prevents infinite loop on empty pages)
            if not data:
                print(f"DEBUG: No data returned, stopping pagination")
                break
            url = paging.get("next")

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

    async def get_documents(
        self,
        matter_id: Optional[int] = None,
        fields: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Get all documents, optionally filtered by matter"""
        params = {}
        if matter_id:
            params["matter_id"] = matter_id
        if fields:
            params["fields"] = ",".join(fields)
        async for doc in self.get_paginated("documents", params):
            yield doc

    async def get_document(self, document_id: int) -> Dict[str, Any]:
        """Get a single document by ID"""
        response = await self.get(f"documents/{document_id}")
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


async def get_clio_user_info(access_token: str) -> Dict[str, Any]:
    """
    Get the current Clio user's information.
    Uses the /users/who_am_i endpoint.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.clio_api_url}/users/who_am_i",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )
        response.raise_for_status()
        return response.json().get("data", {})
