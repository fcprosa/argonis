"""
Screening result models shared across OFAC, OpenSanctions, and adverse media.

Every screening hit carries:
  - matched: bool       — was there a match above threshold?
  - confidence: float   — 0.0–1.0 match confidence
  - matched_entry: dict — the matched record details
  - source_url: str     — click-through URL for analyst verification

This is non-negotiable: analysts MUST be able to click through and verify.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ScreeningMatch(BaseModel):
    """A single match from any screening source."""

    matched: bool
    confidence: float = Field(ge=0.0, le=1.0)
    matched_entry: dict[str, Any] = Field(default_factory=dict)
    source_url: str
    list_name: str  # "OFAC_SDN", "UN_CONSOLIDATED", "EU_SANCTIONS", "PEP", "adverse_media"
    match_type: Literal["exact", "fuzzy", "alias", "phonetic", "keyword"] = "fuzzy"
    entity_name_queried: str
    entity_name_matched: str | None = None
    screened_at: datetime = Field(default_factory=datetime.utcnow)


class ScreeningRequest(BaseModel):
    """Input for the unified screen() function."""

    name: str
    dob: str | None = None          # ISO 8601 date string
    nationality: str | None = None  # ISO 3166-1 alpha-2
    entity_type: str | None = None  # "person" or "organization"


class ScreeningResponse(BaseModel):
    """Aggregated results from all screening sources."""

    entity_name: str
    results: list[ScreeningMatch]
    sources_queried: list[str]
    screened_at: datetime = Field(default_factory=datetime.utcnow)
    highest_confidence: float = 0.0
    has_match: bool = False

    def model_post_init(self, __context: Any) -> None:
        if self.results:
            self.highest_confidence = max(r.confidence for r in self.results if r.matched)  if any(r.matched for r in self.results) else 0.0
            self.has_match = any(r.matched for r in self.results)


class AdverseMediaArticle(BaseModel):
    """A single adverse media article found via search."""

    url: str
    title: str
    snippet: str
    query_used: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    claude_summary: str | None = None


class AdverseMediaResponse(BaseModel):
    """Adverse media screening results for an entity."""

    entity_name: str
    articles: list[AdverseMediaArticle]
    queries_used: list[str]
    total_articles_found: int = 0
    screened_at: datetime = Field(default_factory=datetime.utcnow)
