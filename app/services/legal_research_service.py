"""
Legal Research Service - Integration with CourtListener API

Provides search functionality for relevant case law based on case context.
Uses CourtListener (Free Law Project) as the primary source for legal research.
"""
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


# Jurisdiction patterns for detecting court from case numbers
JURISDICTION_PATTERNS = {
    "LASC": {"state": "cal", "court_type": "state"},
    "SACV": {"state": "cal", "court_type": "federal"},
    "CV": {"state": "cal", "court_type": "federal"},
    "2:": {"court_type": "federal"},
    "1:": {"court_type": "federal"},
    "3:": {"court_type": "federal"},
    "4:": {"court_type": "federal"},
    "5:": {"court_type": "federal"},
    "6:": {"court_type": "federal"},
    "7:": {"court_type": "federal"},
    "8:": {"court_type": "federal"},
    "9:": {"court_type": "federal"},
}


@dataclass
class CaseLawResult:
    """A case law search result from CourtListener"""
    id: int
    case_name: str
    citation: Optional[str]
    court: str
    date_filed: Optional[str]
    snippet: str
    absolute_url: str
    pdf_url: Optional[str] = None
    relevance_score: float = 0.0


class LegalResearchService:
    """
    Service for searching and retrieving legal case law from CourtListener.

    CourtListener API docs: https://www.courtlistener.com/help/api/
    """

    BASE_URL = "https://www.courtlistener.com/api/rest/v4"
    SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"

    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize the legal research service.

        Args:
            api_token: Optional CourtListener API token for higher rate limits
        """
        self.api_token = api_token
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "AIWitnessOrganizer/1.0"
        }
        if api_token:
            self.headers["Authorization"] = f"Token {api_token}"

    def detect_jurisdiction(self, case_number: str) -> Dict[str, str]:
        """
        Detect jurisdiction from case number format.

        Args:
            case_number: The case/matter number (e.g., "LASC BC123456")

        Returns:
            Dict with state and court_type keys
        """
        if not case_number:
            return {"state": "cal", "court_type": "state"}  # Default to California

        case_upper = case_number.upper()

        for prefix, jurisdiction in JURISDICTION_PATTERNS.items():
            if case_upper.startswith(prefix) or prefix in case_upper:
                return jurisdiction

        # Default to California state court
        return {"state": "cal", "court_type": "state"}

    async def search_case_law(
        self,
        query: str,
        jurisdiction: Optional[Dict[str, str]] = None,
        max_results: int = 10,
        date_after: Optional[str] = None
    ) -> List[CaseLawResult]:
        """
        Search CourtListener for relevant case law.

        Args:
            query: Search query text
            jurisdiction: Optional jurisdiction filter {"state": "cal", "court_type": "federal"}
            max_results: Maximum number of results to return
            date_after: Only return cases filed after this date (YYYY-MM-DD)

        Returns:
            List of CaseLawResult objects
        """
        params = {
            "q": query,
            "type": "o",  # Opinions only
            "order_by": "score desc",
            "page_size": min(max_results, 20),  # CourtListener max is 20
        }

        # Add jurisdiction filters
        # Note: CourtListener court parameter doesn't support wildcards
        # Multiple courts can be specified space-separated
        if jurisdiction:
            if jurisdiction.get("court_type") == "federal":
                # Federal courts in California region
                params["court"] = "ca9 cacd caed cand casd"
            elif jurisdiction.get("state"):
                # State courts - use state abbreviation without wildcard
                # Common California courts: cal (Supreme), calctapp (Court of Appeal)
                state = jurisdiction["state"].lower()
                if state == "cal":
                    params["court"] = "cal calctapp"
                else:
                    params["court"] = state

        if date_after:
            params["filed_after"] = date_after

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self.SEARCH_URL,
                    params=params,
                    headers=self.headers
                )
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                return self._format_results(results)

        except httpx.HTTPStatusError as e:
            logger.error(f"CourtListener API error: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Error searching CourtListener: {e}")
            return []

    def _format_results(self, results: List[Dict]) -> List[CaseLawResult]:
        """Format raw API results into CaseLawResult objects."""
        formatted = []

        for r in results:
            # Get citation - can be a list or string
            citation = None
            citations = r.get("citation", [])
            if isinstance(citations, list) and citations:
                citation = citations[0]
            elif isinstance(citations, str):
                citation = citations

            # Get snippet/summary
            snippet = r.get("snippet", "") or r.get("text", "")[:300]
            # Clean HTML tags from snippet, but preserve <mark> tags for highlighting
            # First, temporarily replace mark tags
            snippet = snippet.replace("<mark>", "{{MARK_START}}")
            snippet = snippet.replace("</mark>", "{{MARK_END}}")
            # Remove all other HTML tags
            snippet = re.sub(r'<[^>]+>', '', snippet)
            # Restore mark tags
            snippet = snippet.replace("{{MARK_START}}", "<mark>")
            snippet = snippet.replace("{{MARK_END}}", "</mark>")

            # Build absolute URL
            absolute_url = r.get("absolute_url", "")
            if absolute_url and not absolute_url.startswith("http"):
                absolute_url = f"https://www.courtlistener.com{absolute_url}"

            # Get relevance score safely
            try:
                score = float(r.get("score", 0) or 0)
            except (TypeError, ValueError):
                score = 0.0

            # Get PDF URL - can be in local_path or nested in opinions
            pdf_url = r.get("local_path")
            if not pdf_url:
                opinions = r.get("opinions", [])
                if opinions and isinstance(opinions, list):
                    pdf_url = opinions[0].get("local_path") if opinions[0] else None

            formatted.append(CaseLawResult(
                id=r.get("id") or r.get("cluster_id", 0),
                case_name=r.get("caseName", r.get("case_name", "Unknown Case")),
                citation=citation,
                court=r.get("court", r.get("court_id", "Unknown Court")),
                date_filed=r.get("dateFiled", r.get("date_filed")),
                snippet=snippet[:500],
                absolute_url=absolute_url,
                pdf_url=pdf_url,
                relevance_score=score
            ))

        return formatted

    async def get_opinion_details(self, opinion_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific opinion.

        Args:
            opinion_id: The CourtListener opinion ID

        Returns:
            Opinion details dict or None
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/opinions/{opinion_id}/",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching opinion {opinion_id}: {e}")
            return None

    async def download_opinion_pdf(self, opinion_id: int) -> Optional[bytes]:
        """
        Download opinion as PDF if available.

        Args:
            opinion_id: The CourtListener opinion ID

        Returns:
            PDF bytes or None if not available
        """
        try:
            # First get opinion details to find PDF URL
            details = await self.get_opinion_details(opinion_id)
            if not details:
                return None

            # Check for local PDF path
            pdf_path = details.get("local_path")
            if pdf_path:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    pdf_url = f"https://storage.courtlistener.com/{pdf_path}"
                    response = await client.get(pdf_url)
                    if response.status_code == 200:
                        return response.content

            # Fallback: Try to get HTML and convert (would need additional library)
            logger.warning(f"No PDF available for opinion {opinion_id}")
            return None

        except Exception as e:
            logger.error(f"Error downloading opinion PDF {opinion_id}: {e}")
            return None

    def build_search_queries(
        self,
        claims: List[Dict[str, Any]],
        witness_observations: List[str],
        max_queries: int = 5
    ) -> List[str]:
        """
        Build search queries from case claims and witness observations.

        Args:
            claims: List of claim dicts with 'claim_text' key
            witness_observations: List of key witness observations
            max_queries: Maximum number of queries to generate

        Returns:
            List of search query strings
        """
        queries = []

        # Build queries from claims (most important)
        for claim in claims[:3]:
            claim_text = claim.get("claim_text", "")[:150]
            if claim_text:
                # Extract key legal concepts
                queries.append(claim_text)

        # Build queries from witness observations
        for obs in witness_observations[:2]:
            if obs and len(obs) > 20:
                queries.append(obs[:150])

        return queries[:max_queries]


# Singleton instance
_legal_research_service: Optional[LegalResearchService] = None


def get_legal_research_service() -> LegalResearchService:
    """Get or create the legal research service singleton."""
    global _legal_research_service
    if _legal_research_service is None:
        _legal_research_service = LegalResearchService()
    return _legal_research_service
