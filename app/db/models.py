"""SQLAlchemy database models"""
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey,
    Enum, JSON, Float, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class SubscriptionTier(str, PyEnum):
    """Subscription tier levels"""
    FREE = "free"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class JobStatus(str, PyEnum):
    """Status of a processing job"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WitnessRole(str, PyEnum):
    """Role classification for witnesses"""
    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"
    EYEWITNESS = "eyewitness"
    EXPERT = "expert"
    ATTORNEY = "attorney"
    PHYSICIAN = "physician"
    POLICE_OFFICER = "police_officer"
    FAMILY_MEMBER = "family_member"
    COLLEAGUE = "colleague"
    BYSTANDER = "bystander"
    MENTIONED = "mentioned"
    OTHER = "other"


class ImportanceLevel(str, PyEnum):
    """Importance classification for witnesses (legacy - use RelevanceLevel)"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RelevanceLevel(str, PyEnum):
    """Relevance classification for witnesses based on legal claims"""
    HIGHLY_RELEVANT = "highly_relevant"
    RELEVANT = "relevant"
    SOMEWHAT_RELEVANT = "somewhat_relevant"
    NOT_RELEVANT = "not_relevant"


class Organization(Base):
    """Law firm organization for multi-user billing"""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # Firm name
    clio_account_id = Column(String(128), unique=True, nullable=True, index=True)

    # Stripe billing
    stripe_customer_id = Column(String(255), nullable=True, unique=True)
    stripe_subscription_id = Column(String(255), nullable=True, unique=True)

    # Subscription status
    subscription_status = Column(String(50), default="free", nullable=False)  # free, active, past_due, canceled
    subscription_tier = Column(String(50), default="free", nullable=False)  # free, firm
    user_count = Column(Integer, default=1, nullable=False)  # Billable users
    current_period_end = Column(DateTime, nullable=True)

    # Bonus credits from top-ups (shared across org)
    bonus_credits = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    users = relationship("User", back_populates="organization")
    job_counter = relationship("OrganizationJobCounter", back_populates="organization", uselist=False)


class OrganizationJobCounter(Base):
    """Atomic job counter per organization for sequential job numbers"""
    __tablename__ = "organization_job_counters"

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    job_counter = Column(Integer, default=0, nullable=False)

    organization = relationship("Organization", back_populates="job_counter")


class User(Base):
    """User model - linked to Clio OAuth"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    clio_user_id = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=True)

    # Organization (firm) membership
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    is_admin = Column(Boolean, default=False, nullable=False)  # Can make purchases for org

    # Legacy fields (subscription now on Organization)
    subscription_tier = Column(
        Enum(SubscriptionTier),
        default=SubscriptionTier.FREE,
        nullable=False
    )
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="users")
    clio_integration = relationship("ClioIntegration", back_populates="user", uselist=False)
    matters = relationship("Matter", back_populates="user")
    processing_jobs = relationship("ProcessingJob", back_populates="user")
    credit_usage = relationship("ReportCreditUsage", back_populates="user")


class ClioIntegration(Base):
    """Clio OAuth integration for a user"""
    __tablename__ = "clio_integrations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Encrypted OAuth tokens
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)

    # Clio user info
    clio_user_id = Column(String(128), nullable=True)
    clio_account_id = Column(String(128), nullable=True)
    clio_region = Column(String(10), default="us", nullable=False)  # us or eu

    is_active = Column(Boolean, default=True, nullable=False)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="clio_integration")


class Matter(Base):
    """Legal matter/case from Clio"""
    __tablename__ = "matters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    clio_matter_id = Column(String(128), nullable=False, index=True)

    display_number = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=True)
    practice_area = Column(String(255), nullable=True)
    client_name = Column(String(255), nullable=True)

    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Composite index for user + clio_matter_id
    __table_args__ = (
        Index("ix_matters_user_clio", "user_id", "clio_matter_id", unique=True),
    )

    # Relationships
    user = relationship("User", back_populates="matters")
    documents = relationship("Document", back_populates="matter")


class Document(Base):
    """Document from Clio or uploaded"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    matter_id = Column(Integer, ForeignKey("matters.id", ondelete="CASCADE"), nullable=False)
    clio_document_id = Column(String(128), nullable=True, index=True)
    parent_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)  # For nested attachments

    filename = Column(String(512), nullable=False)
    file_type = Column(String(50), nullable=True)  # pdf, msg, eml, jpg, png, etc.
    file_size = Column(Integer, nullable=True)  # in bytes
    etag = Column(String(255), nullable=True)  # For caching

    # Processing status
    is_processed = Column(Boolean, default=False, nullable=False)
    processing_error = Column(Text, nullable=True)
    processed_at = Column(DateTime, nullable=True)

    # AI analysis cache (JSON of extracted data)
    analysis_cache = Column(JSON, nullable=True)
    analysis_cache_key = Column(String(255), nullable=True)  # etag or hash for cache invalidation

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    matter = relationship("Matter", back_populates="documents")
    parent_document = relationship("Document", remote_side=[id], backref="child_documents")
    witnesses = relationship("Witness", back_populates="document")


class Witness(Base):
    """Extracted witness information"""
    __tablename__ = "witnesses"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)

    # Core witness info
    full_name = Column(String(255), nullable=False, index=True)
    role = Column(Enum(WitnessRole), nullable=False)
    importance = Column(Enum(ImportanceLevel), nullable=False)  # Legacy - use relevance instead

    # New relevance scoring with legal reasoning
    relevance = Column(Enum(RelevanceLevel), nullable=True, default=RelevanceLevel.RELEVANT)
    relevance_reason = Column(Text, nullable=True)  # Legal reasoning tied to claims/defenses

    # Extracted details
    observation = Column(Text, nullable=True)  # What they saw/testified
    source_quote = Column(Text, nullable=True)  # Summary of where/how mentioned (legacy name kept for compat)
    source_page = Column(Integer, nullable=True)  # Page number where found
    context = Column(Text, nullable=True)  # Additional context

    # Contact info (if found)
    email = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)  # Increased for phone+ext formats
    address = Column(Text, nullable=True)

    # AI confidence
    confidence_score = Column(Float, nullable=True)  # 0.0 to 1.0

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    document = relationship("Document", back_populates="witnesses")


class ProcessingJob(Base):
    """Background processing job for document/matter scanning"""
    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    celery_task_id = Column(String(255), nullable=True, index=True)

    # Sequential job number per organization (e.g., "Job #42")
    job_number = Column(Integer, nullable=True, index=True)

    # Job configuration
    job_type = Column(String(50), nullable=False)  # single_matter, full_database
    target_matter_id = Column(Integer, ForeignKey("matters.id"), nullable=True)
    search_witnesses = Column(JSON, nullable=True)  # List of specific names to search for
    include_archived = Column(Boolean, default=False, nullable=False)

    # Progress tracking
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    total_documents = Column(Integer, default=0, nullable=False)
    processed_documents = Column(Integer, default=0, nullable=False)
    failed_documents = Column(Integer, default=0, nullable=False)

    # Results
    total_witnesses_found = Column(Integer, default=0, nullable=False)
    result_summary = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="processing_jobs")
    target_matter = relationship("Matter")


class ReportCreditUsage(Base):
    """Daily report credit usage tracking per user"""
    __tablename__ = "report_credit_usage"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    date = Column(DateTime, nullable=False, index=True)  # Date of usage
    credits_used = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Composite unique constraint: one record per user per day
    __table_args__ = (
        Index("ix_credit_usage_user_date", "user_id", "date", unique=True),
    )

    # Relationships
    user = relationship("User", back_populates="credit_usage")
    organization = relationship("Organization")


class CreditPurchase(Base):
    """Record of credit top-up purchases"""
    __tablename__ = "credit_purchases"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    purchased_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    stripe_payment_intent_id = Column(String(255), nullable=True, unique=True)
    credits_purchased = Column(Integer, nullable=False)
    amount_cents = Column(Integer, nullable=False)  # Amount paid in cents

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    organization = relationship("Organization")
    purchased_by = relationship("User")


class LegalAuthority(Base):
    """Legal authority document (case law, statutes) for RAG context"""
    __tablename__ = "legal_authorities"

    id = Column(Integer, primary_key=True, index=True)
    matter_id = Column(Integer, ForeignKey("matters.id", ondelete="CASCADE"), nullable=False)
    clio_document_id = Column(String(128), nullable=True, index=True)
    clio_folder_id = Column(String(128), nullable=True)

    filename = Column(String(512), nullable=False)
    content_hash = Column(String(64), nullable=True)  # SHA-256 for deduplication
    total_chunks = Column(Integer, default=0, nullable=False)

    # Processing status
    is_processed = Column(Boolean, default=False, nullable=False)
    processing_error = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    matter = relationship("Matter")
    chunks = relationship("LegalAuthorityChunk", back_populates="legal_authority", cascade="all, delete-orphan")


class LegalAuthorityChunk(Base):
    """Text chunk with embedding for semantic search"""
    __tablename__ = "legal_authority_chunks"

    id = Column(Integer, primary_key=True, index=True)
    legal_authority_id = Column(Integer, ForeignKey("legal_authorities.id", ondelete="CASCADE"), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    # Note: embedding column uses pgvector - added via raw SQL migration
    # embedding = Column(Vector(1536))  # Amazon Titan embeddings are 1536 dimensions

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    legal_authority = relationship("LegalAuthority", back_populates="chunks")
