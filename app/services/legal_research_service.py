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
        max_queries: int = 5
    ) -> List[str]:
        """
        Use Claude AI to generate targeted legal search queries.

        Args:
            practice_area: The legal practice area (e.g., "Personal Injury")
            claims: List of claim dicts with 'type', 'text' keys
            witness_summaries: List of witness dicts with 'name', 'role', 'relevance_reason'
            max_queries: Maximum number of queries to generate

        Returns:
            List of search query strings optimized for CourtListener
        """
        if not claims and not witness_summaries:
            return []

        # Format allegations and defenses
        allegations = []
        defenses = []
        for claim in claims:
            claim_type = claim.get("type", "").lower()
            claim_text = claim.get("text", "")[:200]
            if claim_type == "allegation":
                allegations.append(f"- {claim_text}")
            elif claim_type == "defense":
                defenses.append(f"- {claim_text}")
            else:
                allegations.append(f"- {claim_text}")  # Default to allegation

        # Format witness info
        witness_info = []
        for w in witness_summaries[:5]:
            name = w.get("name", "Unknown")
            role = w.get("role", "unknown")
            reason = w.get("relevance_reason", "")[:100]
            if reason:
                witness_info.append(f"- {name} ({role}): {reason}")

        # Build prompt
        prompt = f"""You are a legal research assistant. Generate {max_queries} search queries for CourtListener to find relevant California case law.

Practice Area: {practice_area or "General Litigation"}

Key Allegations:
{chr(10).join(allegations[:5]) if allegations else "None specified"}

Key Defenses:
{chr(10).join(defenses[:3]) if defenses else "None specified"}

Key Witness Context:
{chr(10).join(witness_info) if witness_info else "None specified"}

Generate specific legal search queries that will find precedent cases. Focus on:
- Specific causes of action and legal theories (e.g., "negligent hiring employer liability")
- Key factual patterns from the case
- Relevant California legal standards

Return ONLY the search queries, one per line. No numbering, bullets, or explanations. Each query should be 3-8 words."""

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
                "max_tokens": 500,
                "temperature": 0.3,
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
            user_context: Dict with 'practice_area', 'claims_summary'

        Returns:
            Dict mapping case_id to relevance explanation string
        """
        if not cases:
            return {}

        practice_area = user_context.get("practice_area", "General Litigation")
        claims_summary = user_context.get("claims_summary", "")

        # Format cases for the prompt
        cases_text = []
        for i, case in enumerate(cases[:15], 1):
            case_name = case.get("case_name", "Unknown")[:80]
            court = case.get("court", "Unknown")
            snippet = case.get("snippet", "")[:300]
            # Clean snippet of HTML
            snippet = re.sub(r'<[^>]+>', '', snippet)
            cases_text.append(f"""Case {i}: {case_name}
Court: {court}
Excerpt: {snippet}
---""")

        prompt = f"""You are a legal research assistant. For each case below, write a 1-2 sentence explanation of why it may be relevant to the user's matter. Be SPECIFIC - reference actual legal principles, factual patterns, or procedural issues from each case.

USER'S MATTER:
- Practice Area: {practice_area}
- Key Claims: {claims_summary[:500] if claims_summary else "Not specified"}

CASES TO ANALYZE:
{chr(10).join(cases_text)}

For each case, respond in this exact JSON format:
{{
  "explanations": [
    {{"case_num": 1, "explanation": "Your specific explanation here"}},
    {{"case_num": 2, "explanation": "Your specific explanation here"}}
  ]
}}

Write explanations that:
- Reference specific legal doctrines or standards from the case
- Connect the case facts to the user's matter
- Avoid generic phrases like "may be relevant" without specifics
- Are 1-2 sentences each"""

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
                "max_tokens": 2000,
                "temperature": 0.2,
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
            user_context: Dict with 'practice_area', 'claims_summary'

        Returns:
            Dict mapping case_id to dict with 'issue', 'rule', 'application', 'conclusion', 'utility'
        """
        if not cases:
            return {}

        practice_area = user_context.get("practice_area", "General Litigation")
        claims_summary = user_context.get("claims_summary", "")

        # Format cases for the prompt
        cases_text = []
        for i, case in enumerate(cases[:15], 1):
            case_name = case.get("case_name", "Unknown")[:80]
            court = case.get("court", "Unknown")
            snippet = case.get("snippet", "")[:400]
            # Clean snippet of HTML
            snippet = re.sub(r'<[^>]+>', '', snippet)
            cases_text.append(f"""Case {i}: {case_name}
Court: {court}
Excerpt: {snippet}
---""")

        prompt = f"""You are a legal research analyst creating case briefs. For each case, write a proper IRAC analysis based on the case excerpt.

USER'S CASE:
- Practice Area: {practice_area}
- Claims: {claims_summary[:800] if claims_summary else "General civil litigation"}

CASES TO BRIEF:
{chr(10).join(cases_text)}

Write a proper legal IRAC for each case following this format:

ISSUE: State as a specific legal question. Example: "Whether an employer may be held liable for negligent hiring when it fails to conduct background checks on employees who later cause harm?"

RULE: State the specific legal rule, statute, or test the court applied. Example: "Under California Civil Code § 1714, employers owe a duty of care to third parties when hiring employees, requiring reasonable investigation into an applicant's fitness for the position."

APPLICATION: Explain how the court applied the rule to the specific facts of THIS case. Reference actual facts from the excerpt. Example: "The court found the employer breached its duty because it hired the defendant without verifying his employment history, despite the position requiring interaction with vulnerable populations."

CONCLUSION: State the court's actual holding. Example: "The court held the employer liable for negligent hiring, awarding plaintiff $500,000 in damages."

UTILITY: Explain specifically how this case helps the user's matter. Example: "This case supports plaintiff's negligent hiring claim by establishing that employers in California must conduct background checks for positions involving public contact."

Respond in JSON:
{{
  "analyses": [
    {{
      "case_num": 1,
      "issue": "Whether [specific legal question from this case]?",
      "rule": "[Specific statute, test, or legal standard the court applied]",
      "application": "[How the court applied the rule to THIS case's facts]",
      "conclusion": "[The court's actual holding in this case]",
      "utility": "[How this case specifically helps the user's {practice_area} matter]"
    }}
  ]
}}

CRITICAL: Base your analysis on the actual case excerpt provided. If the excerpt discusses specific facts, parties, or holdings, reference them directly."""

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
                "max_tokens": 4000,
                "temperature": 0.3,
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
