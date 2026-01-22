"""API endpoints for legal research functionality"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, LegalResearchResult, LegalResearchStatus, ProcessingJob, JobStatus, Matter, Witness, CaseClaim, Document, RelevanceLevel
from app.api.deps import get_current_user
from app.services.legal_research_service import get_legal_research_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal-research", tags=["Legal Research"])


def extract_case_characteristics(claims_data: list, witnesses_data: list) -> dict:
    """
    Extract defendant type, harm type, and key facts from case data.

    This provides richer context for AI-generated search queries and analysis.
    """
    facts = {
        "defendant_type": None,
        "harm_type": None,
        "key_facts": [],
        "legal_theories": []
    }

    # Keywords for defendant type detection
    defendant_keywords = {
        "employer": ["employer", "employment", "hired", "employee", "workplace", "job", "termination", "fired"],
        "healthcare_provider": ["hospital", "medical", "physician", "doctor", "nurse", "healthcare", "patient", "clinic"],
        "manufacturer": ["manufacturer", "product", "defect", "manufacturing", "design", "warning label"],
        "property_owner": ["property owner", "landlord", "premises", "tenant", "building", "slip and fall"],
        "government": ["government", "city", "county", "state", "municipal", "police", "officer"],
        "corporation": ["corporation", "company", "business", "LLC", "Inc", "corporate"]
    }

    # Keywords for harm type detection
    harm_keywords = {
        "bodily_injury": ["injury", "harm", "assault", "battery", "physical", "pain", "suffering", "wounded"],
        "emotional_distress": ["emotional distress", "mental anguish", "psychological", "trauma", "harassment"],
        "economic_loss": ["economic loss", "financial", "wages", "income", "lost earnings", "damages"],
        "wrongful_death": ["wrongful death", "death", "deceased", "fatal", "killed"],
        "property_damage": ["property damage", "damaged property", "destroyed", "vandalism"]
    }

    # Legal theory keywords
    legal_theory_keywords = {
        "negligent_hiring": ["negligent hiring", "failed to screen", "background check", "negligent retention"],
        "negligence": ["negligence", "duty of care", "breach of duty", "reasonable care"],
        "premises_liability": ["premises liability", "dangerous condition", "unsafe", "hazard"],
        "vicarious_liability": ["vicarious liability", "respondeat superior", "scope of employment"],
        "intentional_tort": ["intentional", "willful", "deliberate", "assault", "battery"]
    }

    # Analyze claims
    for claim in claims_data:
        text = claim.get("text", "").lower()

        # Detect defendant type
        if not facts["defendant_type"]:
            for dtype, keywords in defendant_keywords.items():
                if any(kw in text for kw in keywords):
                    facts["defendant_type"] = dtype
                    break

        # Detect harm type
        if not facts["harm_type"]:
            for htype, keywords in harm_keywords.items():
                if any(kw in text for kw in keywords):
                    facts["harm_type"] = htype
                    break

        # Detect legal theories
        for theory, keywords in legal_theory_keywords.items():
            if theory not in facts["legal_theories"]:
                if any(kw in text for kw in keywords):
                    facts["legal_theories"].append(theory)

    # Extract key facts from witness observations
    for w in witnesses_data[:5]:
        observation = w.get("observation")
        if observation:
            # Keep first 300 chars of meaningful observations
            facts["key_facts"].append(observation[:300])

    return facts


class CaseLawResultResponse(BaseModel):
    """Response model for a single case law result"""
    id: int
    case_name: str
    citation: Optional[str]
    court: str
    date_filed: Optional[str]
    snippet: str
    absolute_url: str
    matched_query: Optional[str] = None  # The search query that found this case
    relevance_score: Optional[float] = None  # CourtListener relevance score


class LegalResearchResultResponse(BaseModel):
    """Response model for legal research results"""
    id: int
    job_id: int
    status: str
    results: List[CaseLawResultResponse]
    selected_ids: Optional[List[int]]
    created_at: str

    class Config:
        from_attributes = True


class ApproveResearchRequest(BaseModel):
    """Request model for approving legal research"""
    selected_case_ids: List[int]


@router.get("/job/{job_id}")
async def get_legal_research_for_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get legal research results for a specific job.

    Returns the legal research results if they exist and are ready for review.
    """
    # First verify the job belongs to the user
    job_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get the most recent legal research results for this job
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.job_id == job_id,
            LegalResearchResult.user_id == current_user.id
        ).order_by(LegalResearchResult.created_at.desc()).limit(1)
    )
    research = result.scalar_one_or_none()

    if not research:
        return {"has_results": False, "status": None}

    # Format results
    formatted_results = []
    if research.results:
        for r in research.results:
            formatted_results.append({
                "id": r.get("id", 0),
                "case_name": r.get("case_name", "Unknown"),
                "citation": r.get("citation"),
                "court": r.get("court", "Unknown"),
                "date_filed": r.get("date_filed"),
                "snippet": r.get("snippet", "")[:300],
                "absolute_url": r.get("absolute_url", ""),
                "matched_query": r.get("matched_query"),
                "relevance_score": r.get("relevance_score"),
                "relevance_explanation": r.get("relevance_explanation"),
                "irac_issue": r.get("irac_issue"),
                "irac_rule": r.get("irac_rule"),
                "irac_application": r.get("irac_application"),
                "irac_conclusion": r.get("irac_conclusion"),
                "case_utility": r.get("case_utility")
            })

    return {
        "has_results": True,
        "id": research.id,
        "job_id": research.job_id,
        "status": research.status.value,
        "results": formatted_results,
        "selected_ids": research.selected_ids or [],
        "created_at": research.created_at.isoformat() if research.created_at else None
    }


@router.post("/job/{job_id}/generate")
async def generate_legal_research(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate legal research for a job on-demand.

    If results already exist, returns them. Otherwise generates new results.
    """
    # Verify the job belongs to the user and is completed
    job_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job must be completed first")

    if not job.target_matter_id:
        raise HTTPException(status_code=400, detail="Job has no associated matter")

    # Check if results already exist
    existing_result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.job_id == job_id,
            LegalResearchResult.user_id == current_user.id
        ).order_by(LegalResearchResult.created_at.desc()).limit(1)
    )
    existing = existing_result.scalar_one_or_none()

    if existing and existing.results:
        # Return existing results
        formatted_results = []
        for r in existing.results:
            formatted_results.append({
                "id": r.get("id", 0),
                "case_name": r.get("case_name", "Unknown"),
                "citation": r.get("citation"),
                "court": r.get("court", "Unknown"),
                "date_filed": r.get("date_filed"),
                "snippet": r.get("snippet", "")[:300],
                "absolute_url": r.get("absolute_url", ""),
                "matched_query": r.get("matched_query"),
                "relevance_score": r.get("relevance_score"),
                "relevance_explanation": r.get("relevance_explanation"),
                "irac_issue": r.get("irac_issue"),
                "irac_rule": r.get("irac_rule"),
                "irac_application": r.get("irac_application"),
                "irac_conclusion": r.get("irac_conclusion"),
                "case_utility": r.get("case_utility")
            })
        return {
            "has_results": True,
            "id": existing.id,
            "job_id": existing.job_id,
            "status": existing.status.value,
            "results": formatted_results,
            "selected_ids": existing.selected_ids or [],
            "created_at": existing.created_at.isoformat() if existing.created_at else None
        }

    # Generate new results
    try:
        # Get matter info
        matter_result = await db.execute(
            select(Matter).where(Matter.id == job.target_matter_id)
        )
        matter = matter_result.scalar_one_or_none()

        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")

        # Get legal research service
        legal_service = get_legal_research_service()
        jurisdiction = legal_service.detect_jurisdiction(matter.display_number or "")
        practice_area = matter.practice_area or "General Litigation"

        # Get case claims with types for richer context
        claims_result = await db.execute(
            select(CaseClaim).where(
                CaseClaim.matter_id == job.target_matter_id
            ).order_by(CaseClaim.confidence_score.desc().nullslast()).limit(10)
        )
        claims = claims_result.scalars().all()
        claims_data = [
            {
                "type": c.claim_type.value if c.claim_type else "allegation",
                "text": c.claim_text,
                "confidence": c.confidence_score
            }
            for c in claims
        ]
        # Legacy format for fallback
        claim_dicts = [{"claim_text": c.claim_text} for c in claims]

        # Get witness summaries with roles and relevance reasons
        witness_result = await db.execute(
            select(Witness)
            .join(Document, Witness.document_id == Document.id)
            .where(
                Document.matter_id == job.target_matter_id,
                Witness.relevance.in_([RelevanceLevel.HIGHLY_RELEVANT, RelevanceLevel.RELEVANT])
            ).limit(10)
        )
        witnesses = witness_result.scalars().all()
        witnesses_data = [
            {
                "name": w.full_name,
                "role": w.role.value if w.role else "unknown",
                "relevance_reason": w.relevance_reason,
                "observation": w.observation[:200] if w.observation else None
            }
            for w in witnesses
        ]
        # Legacy format for fallback
        witness_observations = [w.observation for w in witnesses if w.observation]

        # Extract case characteristics for richer context
        case_facts = extract_case_characteristics(claims_data, witnesses_data)

        # Build comprehensive user_context early so it can be used for query generation
        allegations = [
            {
                "text": c["text"],
                "confidence": c.get("confidence", 0),
                "type": c.get("type", "allegation")
            }
            for c in claims_data if c.get("type") == "allegation"
        ]
        defenses = [c["text"] for c in claims_data if c.get("type") == "defense"]

        # Build witness context for claims_summary
        witness_context = []
        for w in witnesses_data[:5]:
            w_info = f"{w['name']} ({w['role']})"
            if w.get("relevance_reason"):
                w_info += f": {w['relevance_reason']}"
            if w.get("observation"):
                w_info += f" - Observed: {w['observation']}"
            witness_context.append(w_info)

        # Build claims summary for display
        claims_parts = []
        if allegations:
            claims_parts.append(f"ALLEGATIONS: {'; '.join(a['text'][:200] for a in allegations[:5])}")
        if defenses:
            claims_parts.append(f"DEFENSES: {'; '.join(defenses[:3])}")
        if witness_context:
            claims_parts.append(f"KEY WITNESSES: {'; '.join(witness_context)}")

        claims_summary = " | ".join(claims_parts) if claims_parts else f"Matter: {matter.description or matter.display_number}"

        # Comprehensive user_context for AI analysis
        user_context = {
            "practice_area": practice_area,
            "jurisdiction": jurisdiction,
            "defendant_type": case_facts["defendant_type"],
            "harm_type": case_facts["harm_type"],
            "legal_theories": case_facts["legal_theories"],
            "allegations": allegations[:5],
            "defenses": defenses[:3],
            "key_facts": case_facts["key_facts"],
            "witnesses": [
                {
                    "name": w["name"],
                    "role": w["role"],
                    "observation": w.get("observation", "")
                }
                for w in witnesses_data[:5]
            ],
            "claims_summary": claims_summary[:2000]
        }

        logger.info(f"Built user_context: defendant_type={case_facts['defendant_type']}, harm_type={case_facts['harm_type']}, legal_theories={case_facts['legal_theories']}")

        # Try AI-generated queries first with full user_context
        queries = await legal_service.generate_ai_search_queries(
            practice_area=practice_area,
            claims=claims_data,
            witness_summaries=witnesses_data,
            user_context=user_context,
            max_queries=5
        )

        # Fallback to keyword-based if AI fails
        if not queries:
            logger.info("AI query generation returned empty, falling back to keyword-based")
            queries = legal_service.build_search_queries(
                claims=claim_dicts,
                witness_observations=witness_observations,
                max_queries=5
            )

        if not queries:
            # No queries generated - return empty results
            return {
                "has_results": False,
                "status": None,
                "message": "No search queries could be generated from case data"
            }

        logger.info(f"Using {len(queries)} queries for legal research: {queries}")

        # Search CourtListener
        all_results = []
        seen_ids = set()
        for query in queries:
            try:
                results = await legal_service.search_case_law(
                    query=query,
                    jurisdiction=jurisdiction,
                    max_results=5
                )
                for r in results:
                    if r.id not in seen_ids:
                        seen_ids.add(r.id)
                        r.matched_query = query
                        all_results.append(r)
            except Exception as e:
                logger.warning(f"Legal research query failed: {query[:50]}... Error: {e}")

        if not all_results:
            return {
                "has_results": False,
                "status": None,
                "message": "No relevant case law found"
            }

        # Filter out criminal cases - they're never relevant to civil matters
        CRIMINAL_KEYWORDS = [
            "people v.", "state v.", "united states v.", "commonwealth v.",
            "murder", "manslaughter", "homicide", "death penalty", "capital case",
            "criminal appeal", "penal code", "defendant convicted",
            "guilty", "sentence", "imprisonment", "incarceration",
            "prosecution", "prosecutor", "district attorney",
            "felony", "misdemeanor", "probation", "parole"
        ]

        def is_criminal_case(case) -> bool:
            """Check if a case appears to be criminal based on name and snippet."""
            text = f"{case.case_name} {case.snippet or ''}".lower()
            # Check for criminal case naming patterns
            if text.startswith("people v") or text.startswith("state v") or text.startswith("united states v"):
                return True
            # Check for criminal keywords (need 2+ matches to be sure)
            matches = sum(1 for kw in CRIMINAL_KEYWORDS if kw in text)
            return matches >= 2

        original_count = len(all_results)
        all_results = [r for r in all_results if not is_criminal_case(r)]
        if original_count != len(all_results):
            logger.info(f"Filtered out {original_count - len(all_results)} criminal cases")

        if not all_results:
            return {
                "has_results": False,
                "status": None,
                "message": "No relevant civil case law found (criminal cases filtered)"
            }

        # Limit to top 15 results
        all_results = all_results[:15]

        # Fetch opinion text for cases with short snippets (need more context for analysis)
        logger.info("Fetching opinion text for cases with short snippets...")
        for r in all_results:
            if not r.snippet or len(r.snippet.strip()) < 1000:
                try:
                    opinion_text = await legal_service.get_opinion_text(r.id)
                    if opinion_text:
                        r.snippet = opinion_text[:2000]  # Use first 2000 chars for better analysis
                        logger.info(f"Fetched opinion text for case {r.id}: {len(r.snippet)} chars")
                except Exception as e:
                    logger.warning(f"Failed to fetch opinion text for {r.id}: {e}")

        # Prepare cases for AI analysis
        cases_for_analysis = [
            {
                "id": r.id,
                "case_name": r.case_name,
                "snippet": r.snippet,
                "court": r.court
            }
            for r in all_results
        ]
        relevance_results = await legal_service.analyze_case_relevance_batch(
            cases=cases_for_analysis,
            user_context=user_context
        )

        # Apply relevance explanations and scores to results
        # Filter out cases with low relevance scores (< 5)
        MIN_RELEVANCE_SCORE = 5
        filtered_results = []
        for r in all_results:
            relevance_data = relevance_results.get(r.id, {})
            r.relevance_explanation = relevance_data.get("explanation") if isinstance(relevance_data, dict) else relevance_data
            ai_score = relevance_data.get("score", 5) if isinstance(relevance_data, dict) else 5
            r.relevance_score = float(ai_score)  # Use AI's relevance score

            if ai_score >= MIN_RELEVANCE_SCORE:
                filtered_results.append(r)
            else:
                logger.info(f"Filtering out case {r.id} ({r.case_name[:50]}...) - relevance score {ai_score} < {MIN_RELEVANCE_SCORE}")

        logger.info(f"Filtered from {len(all_results)} to {len(filtered_results)} cases (removed {len(all_results) - len(filtered_results)} irrelevant)")
        all_results = filtered_results

        if not all_results:
            return {
                "has_results": False,
                "status": None,
                "message": "No relevant case law found after filtering"
            }

        # Sort by relevance score descending, limit to top 10 for IRAC analysis
        all_results.sort(key=lambda x: x.relevance_score, reverse=True)
        cases_for_irac = all_results[:10]  # Limit to top 10 to avoid JSON truncation

        # Update cases_for_analysis with only top results
        cases_for_analysis = [
            {
                "id": r.id,
                "case_name": r.case_name,
                "snippet": r.snippet,
                "court": r.court
            }
            for r in cases_for_irac
        ]

        # Generate IRAC analysis only for top relevant cases (batched)
        irac_analyses = await legal_service.analyze_case_irac_batch(
            cases=cases_for_analysis,
            user_context=user_context
        )

        # Apply IRAC analysis to results
        for r in all_results:
            irac = irac_analyses.get(r.id, {})
            r.irac_issue = irac.get("issue")
            r.irac_rule = irac.get("rule")
            r.irac_application = irac.get("application")
            r.irac_conclusion = irac.get("conclusion")
            r.case_utility = irac.get("utility")

        # Save results to database
        results_json = [
            {
                "id": r.id,
                "case_name": r.case_name,
                "citation": r.citation,
                "court": r.court,
                "date_filed": r.date_filed,
                "snippet": r.snippet,
                "absolute_url": r.absolute_url,
                "pdf_url": r.pdf_url,
                "relevance_score": r.relevance_score,
                "matched_query": r.matched_query,
                "relevance_explanation": r.relevance_explanation,
                "irac_issue": r.irac_issue,
                "irac_rule": r.irac_rule,
                "irac_application": r.irac_application,
                "irac_conclusion": r.irac_conclusion,
                "case_utility": r.case_utility
            }
            for r in all_results
        ]

        research_record = LegalResearchResult(
            job_id=job_id,
            user_id=current_user.id,
            matter_id=job.target_matter_id,
            status=LegalResearchStatus.READY,
            results=results_json,
            selected_ids=[]
        )
        db.add(research_record)
        await db.commit()
        await db.refresh(research_record)

        # Format and return
        formatted_results = []
        for r in results_json:
            formatted_results.append({
                "id": r.get("id", 0),
                "case_name": r.get("case_name", "Unknown"),
                "citation": r.get("citation"),
                "court": r.get("court", "Unknown"),
                "date_filed": r.get("date_filed"),
                "snippet": r.get("snippet", "")[:300],
                "absolute_url": r.get("absolute_url", ""),
                "matched_query": r.get("matched_query"),
                "relevance_score": r.get("relevance_score"),
                "relevance_explanation": r.get("relevance_explanation"),
                "irac_issue": r.get("irac_issue"),
                "irac_rule": r.get("irac_rule"),
                "irac_application": r.get("irac_application"),
                "irac_conclusion": r.get("irac_conclusion"),
                "case_utility": r.get("case_utility")
            })

        return {
            "has_results": True,
            "id": research_record.id,
            "job_id": job_id,
            "status": "ready",
            "results": formatted_results,
            "selected_ids": [],
            "created_at": research_record.created_at.isoformat() if research_record.created_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to generate legal research for job {job_id}")
        raise HTTPException(status_code=500, detail=f"Failed to generate legal research: {str(e)}")


@router.post("/{research_id}/approve")
async def approve_legal_research(
    research_id: int,
    request: ApproveResearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Approve selected cases from legal research and save to Clio.

    This queues a background task to download the selected cases and
    upload them to a "Legal Research" folder in the matter's Clio documents.
    """
    # Get the research record
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.id == research_id,
            LegalResearchResult.user_id == current_user.id
        )
    )
    research = result.scalar_one_or_none()

    if not research:
        raise HTTPException(status_code=404, detail="Legal research not found")

    if research.status not in [LegalResearchStatus.READY, LegalResearchStatus.PENDING]:
        raise HTTPException(
            status_code=400,
            detail=f"Research cannot be approved in {research.status.value} status"
        )

    # Update the research with selected IDs
    research.selected_ids = request.selected_case_ids
    research.status = LegalResearchStatus.APPROVED
    research.reviewed_at = datetime.utcnow()

    await db.commit()

    # Queue background task to save to Clio
    from app.worker.tasks import save_legal_research_to_clio
    save_legal_research_to_clio.delay(research_id)

    return {
        "status": "approved",
        "message": f"Saving {len(request.selected_case_ids)} cases to Clio",
        "research_id": research_id
    }


@router.post("/{research_id}/dismiss")
async def dismiss_legal_research(
    research_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Dismiss legal research results.

    The user doesn't want to save any of the suggested cases.
    """
    # Get the research record
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.id == research_id,
            LegalResearchResult.user_id == current_user.id
        )
    )
    research = result.scalar_one_or_none()

    if not research:
        raise HTTPException(status_code=404, detail="Legal research not found")

    # Update status
    research.status = LegalResearchStatus.DISMISSED
    research.reviewed_at = datetime.utcnow()

    await db.commit()

    return {
        "status": "dismissed",
        "message": "Legal research dismissed",
        "research_id": research_id
    }


@router.get("/pending")
async def get_pending_legal_research(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all pending legal research that needs user review.

    Returns a list of jobs that have legal research results ready for review.
    """
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.user_id == current_user.id,
            LegalResearchResult.status == LegalResearchStatus.READY
        ).order_by(LegalResearchResult.created_at.desc())
    )
    research_list = result.scalars().all()

    return {
        "pending_count": len(research_list),
        "items": [
            {
                "id": r.id,
                "job_id": r.job_id,
                "matter_id": r.matter_id,
                "result_count": len(r.results) if r.results else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in research_list
        ]
    }


@router.delete("/job/{job_id}")
async def delete_legal_research_for_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete legal research results for a specific job.

    This allows re-running legal research with updated query logic.
    After deletion, clicking "Case Law" will generate fresh results.
    """
    from sqlalchemy import delete

    # Verify the job belongs to the user
    job_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete all legal research results for this job
    await db.execute(
        delete(LegalResearchResult).where(
            LegalResearchResult.job_id == job_id,
            LegalResearchResult.user_id == current_user.id
        )
    )
    await db.commit()

    return {
        "status": "deleted",
        "message": "Legal research results deleted. Click 'Case Law' to generate new results.",
        "job_id": job_id
    }
