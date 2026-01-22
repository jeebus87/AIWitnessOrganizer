"""
Legal Research Service - Integration with CourtListener API

Provides search functionality for relevant case law based on case context.
Uses CourtListener (Free Law Project) as the primary source for legal research.
Uses AWS Bedrock Claude for AI-powered query generation and relevance analysis.
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import httpx
import boto3
from botocore.config import Config

from app.core.config import settings

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
    matched_query: Optional[str] = None  # The search query that found this case
    relevance_explanation: Optional[str] = None  # AI-generated explanation of relevance to user's case
    # IRAC analysis fields
    irac_issue: Optional[str] = None
    irac_rule: Optional[str] = None
    irac_application: Optional[str] = None
    irac_conclusion: Optional[str] = None
    case_utility: Optional[str] = None  # How this case helps the user's specific matter


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

    async def get_opinion_text(self, cluster_id: int) -> Optional[str]:
        """
        Fetch the actual opinion text for a case cluster.

        Args:
            cluster_id: The CourtListener cluster ID (from search results)

        Returns:
            Opinion text (first 3000 chars) or None
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get cluster details which includes opinions
                response = await client.get(
                    f"{self.BASE_URL}/clusters/{cluster_id}/",
                    headers=self.headers
                )
                if response.status_code != 200:
                    return None

                cluster = response.json()

                # Get the first opinion's text
                opinions = cluster.get("sub_opinions", [])
                if not opinions:
                    return None

                # Fetch the actual opinion
                opinion_url = opinions[0] if isinstance(opinions[0], str) else opinions[0].get("resource_uri")
                if opinion_url:
                    op_response = await client.get(
                        opinion_url if opinion_url.startswith("http") else f"https://www.courtlistener.com{opinion_url}",
                        headers=self.headers
                    )
                    if op_response.status_code == 200:
                        op_data = op_response.json()
                        # Try plain_text first, then html_with_citations, then html
                        text = op_data.get("plain_text") or ""
                        if not text:
                            html = op_data.get("html_with_citations") or op_data.get("html") or ""
                            # Strip HTML tags
                            text = re.sub(r'<[^>]+>', ' ', html)
                            text = re.sub(r'\s+', ' ', text).strip()

                        if text:
                            return text[:3000]  # First 3000 chars

                return None
        except Exception as e:
            logger.error(f"Error fetching opinion text for cluster {cluster_id}: {e}")
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

    async def download_pdf_from_url(self, pdf_url: str) -> Optional[bytes]:
        """
        Download PDF directly from a URL.

        Args:
            pdf_url: Direct URL to the PDF file

        Returns:
            PDF bytes or None if not available
        """
        if not pdf_url:
            return None

        try:
            # Build full URL if it's a relative path
            if pdf_url.startswith("/"):
                pdf_url = f"https://storage.courtlistener.com{pdf_url}"
            elif not pdf_url.startswith("http"):
                pdf_url = f"https://storage.courtlistener.com/{pdf_url}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(pdf_url)
                if response.status_code == 200:
                    logger.info(f"Downloaded PDF from {pdf_url}")
                    return response.content
                else:
                    logger.warning(f"Failed to download PDF from {pdf_url}: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error downloading PDF from {pdf_url}: {e}")
            return None

    # Common causes of action and legal concepts to search for
    LEGAL_CONCEPTS = {
        # Tort causes of action
        "negligence": ["negligence", "duty of care", "breach of duty", "proximate cause", "negligent"],
        "negligent hiring": ["negligent hiring", "negligent retention", "negligent supervision", "employer liability"],
        "premises liability": ["premises liability", "dangerous condition", "slip and fall", "property owner duty"],
        "product liability": ["product liability", "defective product", "manufacturing defect", "design defect", "failure to warn"],
        "medical malpractice": ["medical malpractice", "standard of care", "medical negligence", "healthcare provider"],
        "wrongful death": ["wrongful death", "survival action", "decedent", "wrongful death damages"],
        "assault and battery": ["assault", "battery", "intentional tort", "harmful contact"],
        "false imprisonment": ["false imprisonment", "unlawful detention", "restraint"],
        "intentional infliction": ["intentional infliction of emotional distress", "IIED", "outrageous conduct"],
        "negligent infliction": ["negligent infliction of emotional distress", "NIED", "bystander recovery"],

        # Contract causes of action
        "breach of contract": ["breach of contract", "contractual obligation", "material breach", "anticipatory breach"],
        "breach of warranty": ["breach of warranty", "express warranty", "implied warranty", "merchantability"],
        "fraud": ["fraud", "fraudulent misrepresentation", "intentional misrepresentation", "fraudulent inducement"],
        "negligent misrepresentation": ["negligent misrepresentation", "false statement", "justifiable reliance"],
        "breach of fiduciary duty": ["breach of fiduciary duty", "fiduciary relationship", "fiduciary obligation"],
        "unjust enrichment": ["unjust enrichment", "restitution", "quantum meruit"],

        # Employment causes of action
        "discrimination": ["employment discrimination", "wrongful termination", "discriminatory discharge", "protected class"],
        "harassment": ["workplace harassment", "hostile work environment", "sexual harassment"],
        "retaliation": ["retaliation", "whistleblower", "protected activity", "adverse employment action"],
        "wage and hour": ["wage and hour", "unpaid wages", "overtime", "meal and rest breaks", "FLSA"],

        # Property causes of action
        "trespass": ["trespass", "unlawful entry", "interference with property"],
        "conversion": ["conversion", "wrongful possession", "chattel"],
        "nuisance": ["nuisance", "private nuisance", "public nuisance", "interference with use"],

        # Business torts
        "unfair competition": ["unfair competition", "unfair business practices", "UCL", "Business and Professions Code"],
        "interference": ["tortious interference", "interference with contract", "interference with prospective advantage"],
        "defamation": ["defamation", "libel", "slander", "false statement of fact"],

        # Insurance
        "bad faith": ["insurance bad faith", "breach of implied covenant", "unreasonable denial", "failure to settle"],

        # Civil rights
        "civil rights": ["civil rights violation", "Section 1983", "constitutional violation", "due process"],
    }

    def build_search_queries(
        self,
        claims: List[Dict[str, Any]],
        witness_observations: List[str],
        max_queries: int = 5
    ) -> List[str]:
        """
        Build search queries from case claims by extracting legal concepts.

        Args:
            claims: List of claim dicts with 'claim_text' key
            witness_observations: List of key witness observations
            max_queries: Maximum number of queries to generate

        Returns:
            List of search query strings with legal terminology
        """
        queries = []
        found_concepts = set()

        # Combine all claim text for analysis
        all_claim_text = " ".join(
            claim.get("claim_text", "").lower() for claim in claims
        )

        # Search for legal concepts in claims
        for concept_name, keywords in self.LEGAL_CONCEPTS.items():
            for keyword in keywords:
                if keyword.lower() in all_claim_text:
                    if concept_name not in found_concepts:
                        found_concepts.add(concept_name)
                        # Build a legal search query using the primary term
                        queries.append(keywords[0])  # Use the primary term
                    break

        # If we found legal concepts, use those
        if queries:
            return queries[:max_queries]

        # Fallback: Extract key legal phrases from claims using patterns
        legal_patterns = [
            r"cause of action for (\w+(?:\s+\w+)?)",
            r"(\w+(?:\s+\w+)?) claim",
            r"liable for (\w+(?:\s+\w+)?)",
            r"damages for (\w+(?:\s+\w+)?)",
        ]

        for claim in claims:
            claim_text = claim.get("claim_text", "")
            for pattern in legal_patterns:
                matches = re.findall(pattern, claim_text, re.IGNORECASE)
                for match in matches:
                    clean_match = match.strip().lower()
                    if clean_match and len(clean_match) > 3 and clean_match not in found_concepts:
                        found_concepts.add(clean_match)
                        queries.append(clean_match)

        # If still no queries, use simplified claim text (remove procedural language)
        if not queries:
            for claim in claims[:3]:
                claim_text = claim.get("claim_text", "")
                # Remove common procedural phrases
                simplified = re.sub(
                    r"(named as|plaintiff|defendant|court|case caption|form|document|attached|exhibit|paragraph|\d+)",
                    "",
                    claim_text,
                    flags=re.IGNORECASE
                )
                simplified = " ".join(simplified.split())[:100]
                if simplified and len(simplified) > 20:
                    queries.append(simplified)

        # Final fallback: use witness observations if still no queries
        if not queries and witness_observations:
            for obs in witness_observations[:3]:
                if obs and len(obs) > 20:
                    # Clean up observation text
                    cleaned = re.sub(r"[^\w\s]", " ", obs)
                    cleaned = " ".join(cleaned.split())[:100]
                    if cleaned and len(cleaned) > 15:
                        queries.append(cleaned)

        return queries[:max_queries]

    async def generate_ai_search_queries(
        self,
        practice_area: str,
        claims: List[Dict[str, Any]],
        witness_summaries: List[Dict[str, Any]],
        user_context: Optional[Dict[str, Any]] = None,
        max_queries: int = 5
    ) -> List[str]:
        """
        Use Claude AI to generate targeted legal search queries.

        Args:
            practice_area: The legal practice area (e.g., "Personal Injury")
            claims: List of claim dicts with 'type', 'text' keys
            witness_summaries: List of witness dicts with 'name', 'role', 'relevance_reason'
            user_context: Optional dict with defendant_type, harm_type, key_facts, etc.
            max_queries: Maximum number of queries to generate

        Returns:
            List of search query strings optimized for CourtListener (7-12 words each)
        """
        if not claims and not witness_summaries:
            return []

        user_context = user_context or {}

        # Extract enriched context
        defendant_type = user_context.get("defendant_type", "Unknown")
        harm_type = user_context.get("harm_type", "Unknown")
        legal_theories = user_context.get("legal_theories", [])
        key_facts = user_context.get("key_facts", [])
        jurisdiction = user_context.get("jurisdiction", {})
        state = jurisdiction.get("state", "California") if isinstance(jurisdiction, dict) else "California"

        # Format allegations and defenses
        allegations = []
        defenses = []
        for claim in claims:
            claim_type = claim.get("type", "").lower()
            claim_text = claim.get("text", "")[:300]  # Allow more text for context
            if claim_type == "allegation":
                allegations.append(f"- {claim_text}")
            elif claim_type == "defense":
                defenses.append(f"- {claim_text}")
            else:
                allegations.append(f"- {claim_text}")  # Default to allegation

        # Format witness info with observations
        witness_info = []
        for w in witness_summaries[:5]:
            name = w.get("name", "Unknown")
            role = w.get("role", "unknown")
            reason = w.get("relevance_reason", "")[:150]
            observation = w.get("observation", "")[:150]
            info = f"- {name} ({role})"
            if reason:
                info += f": {reason}"
            if observation:
                info += f" | Observed: {observation}"
            witness_info.append(info)

        # Format key facts from observations
        facts_text = ""
        if key_facts:
            facts_text = "\n".join(f"- {fact[:200]}" for fact in key_facts[:3])

        # Build prompt with richer context for 7-12 word queries
        prompt = f"""You are a legal research assistant. Generate {max_queries} TARGETED search queries for CourtListener to find relevant case law.

CASE CONTEXT:
- Practice Area: {practice_area or "General Litigation"}
- Jurisdiction: {state.upper() if state else "California"}
- Defendant Type: {defendant_type or "Unknown"}
- Harm Type: {harm_type or "Unknown"}
- Legal Theories: {', '.join(legal_theories) if legal_theories else "To be determined from claims"}

PRIMARY ALLEGATIONS (highest priority):
{chr(10).join(allegations[:5]) if allegations else "None specified"}

KEY DEFENSES:
{chr(10).join(defenses[:3]) if defenses else "None specified"}

KEY FACTUAL PATTERNS (from witnesses):
{facts_text if facts_text else "None specified"}

KEY WITNESSES:
{chr(10).join(witness_info) if witness_info else "None specified"}

REQUIREMENTS:
1. Each query MUST be 7-12 words - specific enough to find relevant cases
2. Combine legal theory + fact pattern (e.g., "employer negligent hiring assault customer background check failure")
3. Include jurisdiction-specific terms where relevant (e.g., "California employer duty care")
4. Avoid single-concept queries like "negligence" or "negligent hiring" alone - too broad
5. Focus on the specific defendant type ({defendant_type}) and harm type ({harm_type})

EXAMPLES OF GOOD QUERIES:
- "California employer negligent hiring assault customer background check failure"
- "hospital vicarious liability nurse intentional tort patient harm"
- "premises liability dangerous condition slip fall business invitee California"
- "employer liability employee criminal act scope employment foreseeable"

EXAMPLES OF BAD QUERIES (too short/generic):
- "negligent hiring" (only 2 words)
- "employer liability" (too vague)
- "personal injury" (too broad)

Return ONLY the search queries, one per line. No numbering, bullets, or explanations."""

        try:
            # Use Bedrock Claude
            config = Config(
                region_name=settings.aws_region,
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=60,
                connect_timeout=30
            )
            client = boto3.client(
                service_name="bedrock-runtime",
                config=config,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )

            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 800,  # More tokens for longer queries
                "temperature": 0.5,  # Higher temperature for more creative query combinations
                "messages": [{"role": "user", "content": prompt}]
            }

            # Use Haiku for fast, cheap query generation
            response = client.invoke_model(
                modelId="us.anthropic.claude-3-5-haiku-20241022-v1:0",
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body)
            )

            response_body = json.loads(response["body"].read())
            text_content = response_body.get("content", [{}])[0].get("text", "")

            # Parse queries (one per line)
            queries = []
            for line in text_content.strip().split("\n"):
                line = line.strip()
                # Remove any numbering or bullets
                line = re.sub(r'^[\d\.\-\*\•]+\s*', '', line)
                if line and len(line) > 5 and len(line) < 100:
                    queries.append(line)

            logger.info(f"AI generated {len(queries)} search queries")
            return queries[:max_queries]

        except Exception as e:
            logger.error(f"AI query generation failed: {e}")
            return []

    async def analyze_case_relevance_batch(
        self,
        cases: List[Dict[str, Any]],
        user_context: Dict[str, Any]
    ) -> Dict[int, str]:
        """
        Use Claude AI to analyze relevance of multiple cases in one batch call.

        Args:
            cases: List of case dicts with 'id', 'case_name', 'snippet', 'court'
            user_context: Dict with practice_area, defendant_type, harm_type, allegations, key_facts

        Returns:
            Dict mapping case_id to relevance explanation string
        """
        if not cases:
            return {}

        practice_area = user_context.get("practice_area", "General Litigation")
        defendant_type = user_context.get("defendant_type", "Unknown")
        harm_type = user_context.get("harm_type", "Unknown")
        allegations = user_context.get("allegations", [])
        key_facts = user_context.get("key_facts", [])

        # Format allegations for prompt
        allegations_text = ""
        if allegations:
            allegations_text = "\n".join(f"- {a['text'][:200]}" for a in allegations[:3] if isinstance(a, dict) and a.get('text'))

        # Format key facts
        facts_text = ""
        if key_facts:
            facts_text = "\n".join(f"- {f[:150]}" for f in key_facts[:3])

        # Format cases for the prompt with longer snippets (1000 chars)
        cases_text = []
        for i, case in enumerate(cases[:15], 1):
            case_name = case.get("case_name", "Unknown")[:100]
            court = case.get("court", "Unknown")
            snippet = case.get("snippet", "")[:1000]  # Increased from 300 to 1000
            # Clean snippet of HTML
            snippet = re.sub(r'<[^>]+>', '', snippet)
            cases_text.append(f"""Case {i}: {case_name}
Court: {court}
Excerpt: {snippet}
---""")

        prompt = f"""You are a legal research assistant. Analyze the relevance of each case to the user's specific matter.

USER'S CASE:
- Practice Area: {practice_area}
- Defendant Type: {defendant_type}
- Harm Type: {harm_type}
- Key Allegations:
{allegations_text if allegations_text else "Not specified"}
- Key Facts:
{facts_text if facts_text else "Not specified"}

CASES TO ANALYZE:
{chr(10).join(cases_text)}

For each case, explain in 2-3 sentences:
1. What SPECIFIC legal principle or holding does this case establish?
2. How do the facts COMPARE to the user's facts (defendant type: {defendant_type}, harm: {harm_type})?
3. Is this DIRECTLY relevant (binding on the user's key issue) or TANGENTIALLY relevant (general principles)?

CRITICAL REQUIREMENTS:
- Be SPECIFIC - reference actual holdings, standards, or tests from each case
- COMPARE to the user's specific facts (not generic legal concepts)
- Never say "may be relevant" without explaining HOW and WHY
- Mention if the defendant type or harm type matches the user's case

Respond in JSON:
{{
  "explanations": [
    {{"case_num": 1, "explanation": "Your specific 2-3 sentence explanation"}},
    {{"case_num": 2, "explanation": "Your specific 2-3 sentence explanation"}}
  ]
}}"""

        try:
            config = Config(
                region_name=settings.aws_region,
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=120,
                connect_timeout=30
            )
            client = boto3.client(
                service_name="bedrock-runtime",
                config=config,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )

            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 3000,  # More tokens for detailed explanations
                "temperature": 0.4,  # Higher temperature for more specific, creative connections
                "messages": [{"role": "user", "content": prompt}]
            }

            # Use Sonnet for better reasoning on relevance analysis
            response = client.invoke_model(
                modelId="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body)
            )

            response_body = json.loads(response["body"].read())
            text_content = response_body.get("content", [{}])[0].get("text", "")

            # Parse JSON response
            try:
                # Find JSON in response
                json_match = re.search(r'\{[\s\S]*\}', text_content)
                if json_match:
                    data = json.loads(json_match.group())
                    explanations = data.get("explanations", [])

                    # Map back to case IDs
                    result = {}
                    for exp in explanations:
                        case_num = exp.get("case_num", 0) - 1  # Convert to 0-indexed
                        explanation = exp.get("explanation", "")
                        if 0 <= case_num < len(cases) and explanation:
                            case_id = cases[case_num].get("id")
                            if case_id:
                                result[case_id] = explanation

                    logger.info(f"AI analyzed relevance for {len(result)} cases")
                    return result

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse AI relevance response: {e}")

            return {}

        except Exception as e:
            logger.error(f"AI relevance analysis failed: {e}")
            return {}

    async def analyze_case_irac_batch(
        self,
        cases: List[Dict[str, Any]],
        user_context: Dict[str, Any]
    ) -> Dict[int, Dict[str, str]]:
        """
        Use Claude AI to generate IRAC analysis for multiple cases in one batch call.

        Args:
            cases: List of case dicts with 'id', 'case_name', 'snippet', 'court'
            user_context: Dict with practice_area, defendant_type, harm_type, allegations, key_facts

        Returns:
            Dict mapping case_id to dict with 'issue', 'rule', 'application', 'conclusion', 'utility'
        """
        if not cases:
            return {}

        practice_area = user_context.get("practice_area", "General Litigation")
        defendant_type = user_context.get("defendant_type", "Unknown")
        harm_type = user_context.get("harm_type", "Unknown")
        allegations = user_context.get("allegations", [])
        key_facts = user_context.get("key_facts", [])

        # Format allegations for prompt
        allegations_text = ""
        if allegations:
            allegations_text = "\n".join(f"- {a['text'][:200]}" for a in allegations[:3] if isinstance(a, dict) and a.get('text'))

        # Format key facts
        facts_text = ""
        if key_facts:
            facts_text = "\n".join(f"- {f[:150]}" for f in key_facts[:3])

        # Format cases for the prompt with longer snippets (1500 chars)
        cases_text = []
        for i, case in enumerate(cases[:15], 1):
            case_name = case.get("case_name", "Unknown")[:100]
            court = case.get("court", "Unknown")
            snippet = case.get("snippet", "")[:1500]  # Increased from 400 to 1500
            # Clean snippet of HTML
            snippet = re.sub(r'<[^>]+>', '', snippet)
            cases_text.append(f"""Case {i}: {case_name}
Court: {court}
Excerpt: {snippet}
---""")

        prompt = f"""You are a legal research analyst creating case briefs for an attorney.

USER'S CASE (for relevance comparison):
- Practice Area: {practice_area}
- Position: PLAINTIFF
- Defendant Type: {defendant_type}
- Harm Type: {harm_type}
- Key Allegations:
{allegations_text if allegations_text else "Not specified"}
- Key Factual Patterns:
{facts_text if facts_text else "Not specified"}

CASES TO BRIEF:
{chr(10).join(cases_text)}

For EACH case, provide a proper IRAC analysis:

ISSUE: State the specific legal question as a question.
GOOD: "Whether an employer owes a duty to conduct background checks before hiring for positions with access to vulnerable populations?"
BAD: "The issue is negligent hiring." (not a question, too vague)

RULE: State the SPECIFIC legal rule, statute, or test the court applied. Include citations if visible.
GOOD: "Under California Civil Code § 1714 and the doctrine of respondeat superior, employers must exercise reasonable care in hiring, including conducting background checks when the position involves foreseeable risk of harm to third parties."
BAD: "The rule is that employers must be careful when hiring." (too vague, no citation)

APPLICATION: How did the court apply the rule to THIS case's specific facts? Reference actual parties, facts, and reasoning from the excerpt.
GOOD: "The court found ABC Corp breached its duty because (1) it hired defendant without any background check despite the position involving patient contact; (2) a standard check would have revealed prior assault convictions; (3) the subsequent assault was foreseeable given defendant's history."
BAD: "The court applied the rule to the facts." (no specifics)

CONCLUSION: The court's actual holding and any damages awarded.
GOOD: "The court held ABC Corp liable for negligent hiring, affirming the jury verdict of $350,000 in compensatory damages and denying punitive damages."
BAD: "The plaintiff won." (no details)

UTILITY: How does this case SPECIFICALLY help with the user's {practice_area} matter involving a {defendant_type} and {harm_type}? Compare to user's facts.
GOOD: "This case strongly supports the plaintiff's position because it establishes liability for the same conduct alleged here - failure to conduct background checks for positions involving {harm_type}. The {defendant_type} defendant here faces similar exposure."
BAD: "This case is relevant to the user's case." (no comparison)

Respond in JSON:
{{
  "analyses": [
    {{
      "case_num": 1,
      "issue": "Whether [specific legal question from THIS case as a question]?",
      "rule": "[Specific statute/citation, legal test, and elements required]",
      "application": "[How court applied rule to THIS case's specific facts with party names]",
      "conclusion": "[Court's holding with damages if mentioned]",
      "utility": "[How this helps user's specific {practice_area} case against {defendant_type}]"
    }}
  ]
}}

CRITICAL REQUIREMENTS:
- Base analysis on the ACTUAL case excerpt - reference specific facts, parties, holdings
- The ISSUE must be a question ending with "?"
- The RULE must include specific legal standards, not vague principles
- The APPLICATION must reference specific facts from the excerpt
- The UTILITY must compare to the user's specific case facts"""

        try:
            config = Config(
                region_name=settings.aws_region,
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=180,
                connect_timeout=30
            )
            client = boto3.client(
                service_name="bedrock-runtime",
                config=config,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )

            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 6000,  # More tokens for detailed IRAC analysis
                "temperature": 0.4,  # Higher temperature for more specific analysis
                "messages": [{"role": "user", "content": prompt}]
            }

            # Use Sonnet for better reasoning on IRAC analysis
            response = client.invoke_model(
                modelId="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body)
            )

            response_body = json.loads(response["body"].read())
            text_content = response_body.get("content", [{}])[0].get("text", "")

            # Parse JSON response
            try:
                # Find JSON in response
                json_match = re.search(r'\{[\s\S]*\}', text_content)
                if json_match:
                    data = json.loads(json_match.group())
                    analyses = data.get("analyses", [])

                    # Map back to case IDs
                    result = {}
                    for analysis in analyses:
                        case_num = analysis.get("case_num", 0) - 1  # Convert to 0-indexed
                        if 0 <= case_num < len(cases):
                            case_id = cases[case_num].get("id")
                            if case_id:
                                result[case_id] = {
                                    "issue": analysis.get("issue", ""),
                                    "rule": analysis.get("rule", ""),
                                    "application": analysis.get("application", ""),
                                    "conclusion": analysis.get("conclusion", ""),
                                    "utility": analysis.get("utility", "")
                                }

                    logger.info(f"AI generated IRAC analysis for {len(result)} cases")
                    return result

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse AI IRAC response: {e}")

            return {}

        except Exception as e:
            logger.error(f"AI IRAC analysis failed: {e}")
            return {}


# Singleton instance
_legal_research_service: Optional[LegalResearchService] = None


def get_legal_research_service() -> LegalResearchService:
    """Get or create the legal research service singleton."""
    global _legal_research_service
    if _legal_research_service is None:
        import os
        api_token = os.environ.get("COURTLISTENER_API_TOKEN")
        _legal_research_service = LegalResearchService(api_token=api_token)
        if api_token:
            logger.info("CourtListener API token configured - using authenticated requests")
    return _legal_research_service
