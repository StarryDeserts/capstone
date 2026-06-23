from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Depth(str, Enum):
    quick = "quick"
    standard = "standard"
    deep = "deep"


class Style(str, Enum):
    brief = "brief"
    report = "report"
    bullet = "bullet"


class Strictness(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Verdict(str, Enum):
    supported = "supported"
    contradicted = "contradicted"
    unverifiable = "unverifiable"


Confidence = Field(ge=0.0, le=1.0)


class OrchestratorRequest(BaseModel):
    topic: str
    depth: Depth
    format: Style
    max_sources: Optional[int] = None
    audience: Optional[str] = None


class Finding(BaseModel):
    statement: str
    source_url: str
    source_title: str
    snippet: str
    confidence: float = Confidence
    published_at: Optional[str] = None


class Citation(BaseModel):
    claim: str
    source_url: str
    snippet: str
    confidence: float = Confidence
    verdict: Literal["supported", "contradicted", "unverifiable", "unverified"]


class SubOrder(BaseModel):
    role: str
    service_id: str
    order_id: str
    price_usdc: float
    status: str


class OrchestratorMeta(BaseModel):
    sub_orders: list[SubOrder] = []
    total_cost_usdc: float = 0.0
    model: str


class OrchestratorDeliverable(BaseModel):
    report_markdown: str
    citations: list[Citation] = []
    meta: OrchestratorMeta


class ResearchRequest(BaseModel):
    query: str
    num_sources: int = Field(ge=1)
    recency: Optional[str] = None
    focus: Optional[str] = None


class ResearchDeliverable(BaseModel):
    findings: list[Finding] = []


class Claim(BaseModel):
    statement: str
    source_url: Optional[str] = None


class FactCheckRequest(BaseModel):
    claims: list[Claim]
    strictness: Strictness = Strictness.normal


class VerdictItem(BaseModel):
    statement: str
    verdict: Verdict
    evidence_url: str = ""
    evidence_snippet: str = ""
    confidence: float = Confidence
    notes: Optional[str] = None


class FactCheckDeliverable(BaseModel):
    verdicts: list[VerdictItem] = []


class Reference(BaseModel):
    n: int
    url: str
    title: str


class FormatRequest(BaseModel):
    title: str
    verified_findings: list[Finding] = []
    style: Style
    audience: Optional[str] = None


class FormatDeliverable(BaseModel):
    report_markdown: str
    references: list[Reference] = []
