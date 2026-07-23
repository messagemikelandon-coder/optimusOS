from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import DiagnosticFinding, JobInputProposal, Vehicle
from app.diagnostics_store import _get_finding
from app.models import (
    JobInputProposalListResponse,
    JobInputProposalRead,
    JobInputProposalStatus,
    ProposedJobInputs,
)
from app.shop_store import resolve_shop_id
from app.vehicle_store import vehicle_display_name

PROMPT_VERSION = "job-inputs-v1"

_SYSTEM_PROMPT = (
    "You are an automotive service-writer assistant proposing DRAFT inputs for a "
    "deterministic job compiler. You ONLY suggest: a short evidence summary, "
    "assumptions, an overall confidence, a list of recommended services (each with "
    "a title, a labor-hours ESTIMATE, an optional rationale, and generic part "
    "CATEGORIES), and clarifying questions. Hard rules: never state a price, a part "
    "availability, a specific part number or supplier, a VIN fact, a definitive "
    "diagnosis presented as certain, or any approval/payment state. Labor hours are "
    "estimates to be confirmed by the shop, not authoritative. Part categories are "
    "generic (e.g. 'front brake pads'), never specific priced parts. Base everything "
    "only on the evidence provided; if evidence is insufficient, say so in "
    "assumptions/questions rather than inventing facts."
)


class JobProposalError(ValueError):
    pass


class JobProposalUnavailableError(JobProposalError):
    """The AI provider failed, timed out, or returned output that did not
    validate against the strict schema. Surfaced as a safe error; nothing is
    persisted and no autonomous action is taken."""


class JobInputProposalNotFoundError(JobProposalError):
    pass


@dataclass(frozen=True)
class JobEvidence:
    """The diagnostic evidence handed to the proposer. Only shop-owned finding
    data (already in the database) -- never a secret."""

    vehicle_display: str
    complaint: str | None
    symptoms: str
    tests_performed: str | None
    codes: str | None
    conclusion: str | None
    confidence: str | None
    severity: str | None

    def as_prompt_text(self) -> str:
        parts = [
            f"Vehicle: {self.vehicle_display}",
            f"Complaint (reported): {self.complaint or 'not recorded'}",
            f"Symptoms (observed): {self.symptoms}",
            f"Tests/measurements performed: {self.tests_performed or 'not recorded'}",
            f"Diagnostic codes: {self.codes or 'none'}",
            f"Working conclusion: {self.conclusion or 'not recorded'}",
            f"Stated confidence: {self.confidence or 'not stated'}",
            f"Safety severity: {self.severity or 'not assessed'}",
        ]
        return "\n".join(parts)


class JobInputProposer(ABC):
    """Provider-neutral interface. Implementations propose structured, draft-only
    Job Compiler inputs from diagnostic evidence. The concrete provider is chosen
    at the call site; tests inject a deterministic fake so CI makes no paid/live
    call."""

    model: str = "unknown"
    prompt_version: str = PROMPT_VERSION

    @abstractmethod
    async def propose(self, evidence: JobEvidence) -> ProposedJobInputs:
        """Return a validated ``ProposedJobInputs`` or raise
        ``JobProposalUnavailableError`` on any provider/parse failure."""
        raise NotImplementedError


class OpenAIJobInputProposer(JobInputProposer):
    """Real OpenAI-backed provider. Never invoked in CI (tests inject a fake and
    the route 503s when no key is configured). Uses structured output so the
    model must conform to ``ProposedJobInputs``; any failure/timeout/parse error
    degrades to ``JobProposalUnavailableError`` (safe failure)."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self.model = settings.estimator_model
        self.prompt_version = PROMPT_VERSION
        if client is not None:
            self._client = client
        elif not settings.openai_api_key:
            raise JobProposalUnavailableError("AI proposals are not configured.")
        else:  # pragma: no cover - exercised only with a real key, never in CI
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_timeout_seconds,
            )

    async def propose(self, evidence: JobEvidence) -> ProposedJobInputs:
        try:
            return await asyncio.to_thread(self._propose_sync, evidence)
        except JobProposalUnavailableError:
            raise
        except Exception as exc:
            # Degrade ANY provider error (network, timeout, SDK, parse) to a safe
            # failure -- nothing is persisted and no autonomous action is taken.
            raise JobProposalUnavailableError("The AI proposal service is unavailable.") from exc

    def _propose_sync(self, evidence: JobEvidence) -> ProposedJobInputs:  # pragma: no cover
        response = self._client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": evidence.as_prompt_text()},
            ],
            text_format=ProposedJobInputs,
        )
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, ProposedJobInputs):
            raise JobProposalUnavailableError("The AI proposal did not match the required schema.")
        return validate_proposed_inputs(parsed)


def build_job_input_proposer(settings: Settings) -> JobInputProposer:
    """Factory for the active proposer. Returns the real OpenAI provider (which
    raises ``JobProposalUnavailableError`` if no key is configured). Tests
    override this at the call site to inject a deterministic fake, so CI never
    constructs an OpenAI client or makes a paid/live call."""
    return OpenAIJobInputProposer(settings)


def validate_proposed_inputs(raw: object) -> ProposedJobInputs:
    """Deterministic validation gate for an AI proposal. Parsing through the
    strict ``ProposedJobInputs`` schema (``extra='forbid'``, bounded fields, no
    price/VIN/availability field at all) is the core safety control: a malformed
    payload or one carrying an invented price/VIN/availability field is rejected
    here. Accepts either an already-parsed model or a raw dict."""
    try:
        if isinstance(raw, ProposedJobInputs):
            # Re-validate to enforce the schema even if constructed loosely.
            return ProposedJobInputs.model_validate(raw.model_dump())
        return ProposedJobInputs.model_validate(raw)
    except ValidationError as exc:
        raise JobProposalUnavailableError(
            "The AI proposal was malformed or contained unsupported claims."
        ) from exc


def _load_evidence(
    db: Session, auth: AuthContext, finding_id: int
) -> tuple[DiagnosticFinding, JobEvidence]:
    finding = _get_finding(db, auth, finding_id)
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == finding.vehicle_id, Vehicle.shop_id == finding.shop_id)
    )
    return finding, JobEvidence(
        vehicle_display=vehicle_display_name(vehicle) if vehicle else "Unknown vehicle",
        complaint=finding.complaint,
        symptoms=finding.symptoms,
        tests_performed=finding.tests_performed,
        codes=finding.codes,
        conclusion=finding.conclusion,
        confidence=finding.confidence,
        severity=finding.severity,
    )


def _to_read(proposal: JobInputProposal) -> JobInputProposalRead:
    return JobInputProposalRead(
        id=proposal.id,
        finding_id=proposal.finding_id,
        status=JobInputProposalStatus(proposal.status),
        model=proposal.model,
        prompt_version=proposal.prompt_version,
        validation_status=proposal.validation_status,
        proposal=ProposedJobInputs.model_validate(proposal.payload),
        created_at=ensure_utc(proposal.created_at),
        updated_at=ensure_utc(proposal.updated_at),
    )


async def propose_job_inputs(
    *,
    db: Session,
    auth: AuthContext,
    finding_id: int,
    proposer: JobInputProposer,
) -> JobInputProposalRead:
    """Ask the provider for a draft proposal for a finding, validate it, and
    persist it as an audit record (status ``proposed``). Creates NO estimate,
    work-order, invoice, or compilation -- the proposal is a suggestion the owner
    must review and feed into the deterministic compile flow. The finding is
    loaded shop-scoped first, so a cross-shop finding is rejected before the
    provider is ever called."""
    finding, evidence = _load_evidence(db, auth, finding_id)
    raw = await proposer.propose(evidence)
    validated = validate_proposed_inputs(raw)
    proposal = JobInputProposal(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        finding_id=finding.id,
        status=JobInputProposalStatus.PROPOSED.value,
        model=proposer.model,
        prompt_version=proposer.prompt_version,
        validation_status="valid",
        payload=validated.model_dump(mode="json"),
        created_by_user_id=auth.user.id,
        updated_by_user_id=auth.user.id,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return _to_read(proposal)


def _proposal_query(db: Session, auth: AuthContext) -> Select[tuple[JobInputProposal]]:
    return select(JobInputProposal).where(JobInputProposal.shop_id == effective_shop_id(db, auth))


def _require_proposal(db: Session, auth: AuthContext, proposal_id: int) -> JobInputProposal:
    proposal = db.scalar(_proposal_query(db, auth).where(JobInputProposal.id == proposal_id))
    if proposal is None:
        raise JobInputProposalNotFoundError("Job input proposal not found.")
    return proposal


def get_job_input_proposal(
    *, db: Session, auth: AuthContext, proposal_id: int
) -> JobInputProposalRead:
    return _to_read(_require_proposal(db, auth, proposal_id))


def list_job_input_proposals(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    finding_id: int | None = None,
    status: JobInputProposalStatus | None = None,
) -> JobInputProposalListResponse:
    if page_size > settings.customers_max_page_size:
        raise JobProposalError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise JobProposalError("Page must be 1 or greater.")
    query = _proposal_query(db, auth)
    if finding_id is not None:
        query = query.where(JobInputProposal.finding_id == finding_id)
    if status is not None:
        query = query.where(JobInputProposal.status == status.value)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    proposals = db.scalars(
        query.order_by(JobInputProposal.created_at.desc(), JobInputProposal.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return JobInputProposalListResponse(
        items=[_to_read(proposal) for proposal in proposals],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(proposals) < total,
    )


def set_job_input_proposal_disposition(
    *, db: Session, auth: AuthContext, proposal_id: int, status: JobInputProposalStatus
) -> JobInputProposalRead:
    proposal = _require_proposal(db, auth, proposal_id)
    proposal.status = status.value
    proposal.updated_by_user_id = auth.user.id
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return _to_read(proposal)
