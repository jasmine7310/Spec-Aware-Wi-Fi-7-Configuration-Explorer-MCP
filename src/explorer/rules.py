"""P1 rule registry: loads and checks ``rules.yaml``.

Every P1 rejection cites a rule ID from this registry, so the validator, the campaign
planner and the minimizer all agree on what each rule says and where it comes from.
This module only loads the registry and checks its structure (unique IDs, known
source documents, normative rules backed by a normative source). The code that
enforces each rule's predicate is separate and is tested against the rule's examples.

A rule's ``kind`` says where its authority comes from. Only ``normative`` rules are
Wi-Fi specification rules; ``harness`` and ``policy`` rules keep candidates meaningful
for our experiments, and ``dependency`` rules mark settings that only mean something
together with another one. Passing every rule means "passes modeled rules", never
full 802.11be compliance.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / "rules.yaml"

REGISTRY_VERSION = 1

RuleKind = Literal["normative", "guidance", "dependency", "harness", "policy"]

# draft: the research behind the rule hasn't been reviewed by a second teammate yet.
RuleStatus = Literal["draft", "reviewed"]

# What kind of text a citation points at (docs/references.md):
#   shall         a normative requirement in an IEEE standard
#   note          an IEEE NOTE: informative, never a rule on its own
#   unclassified  other IEEE text (a definition, a table) not recorded as a "shall"
#   guidance      Wi-Fi Alliance deployment guidance
#   code          hostap source or tests
Strength = Literal["shall", "note", "unclassified", "guidance", "code"]
_NORMATIVE_DOC_STRENGTHS = {"shall", "note", "unclassified"}

_STRICT = ConfigDict(strict=True, extra="forbid", frozen=True)


class SourceDoc(BaseModel):
    """A document or code base rules can cite (see docs/references.md)."""

    model_config = _STRICT

    title: str
    version: str
    normative: bool = Field(description="True only for documents with 'shall' requirements.")


class Citation(BaseModel):
    """One place a rule comes from."""

    model_config = _STRICT

    doc: str = Field(description="Key into the registry's sources.")
    location: str = Field(
        description="Section/table for a document; 'path:line' or 'path:start-end' in hostap.")
    strength: Strength
    page: str | None = None
    says: str = Field(min_length=1, description="What this source says, in our own words.")
    checked: str | None = Field(
        default=None,
        description="Who checked the citation against the source, and when; None = unchecked.")


class Examples(BaseModel):
    """Plain-language allowed / disallowed cases; the rule's unit tests encode them."""

    model_config = _STRICT

    allowed: list[str] = Field(min_length=1)
    disallowed: list[str] = Field(min_length=1)


class Rule(BaseModel):
    model_config = _STRICT

    id: str = Field(pattern=r"^[A-Z]+\.[A-Z0-9_]+$")
    title: str
    kind: RuleKind
    status: RuleStatus
    applies_to: list[str] = Field(
        min_length=1, description="Candidate names from surface_candidates.csv.")
    meaning: str = Field(min_length=1)
    predicate: str = Field(min_length=1, description="The check, in plain language.")
    exceptions: list[str] = []
    sources: list[Citation] = Field(min_length=1)
    examples: Examples
    notes: list[str] = []


class RuleRegistry(BaseModel):
    model_config = _STRICT

    version: int
    sources: dict[str, SourceDoc]
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> RuleRegistry:
        if self.version != REGISTRY_VERSION:
            raise ValueError(f"version must be {REGISTRY_VERSION}, got {self.version}")
        ids = [rule.id for rule in self.rules]
        repeated = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if repeated:
            raise ValueError(f"rule IDs must be unique, repeated: {repeated}")
        for rule in self.rules:
            for citation in rule.sources:
                if citation.doc not in self.sources:
                    raise ValueError(f"{rule.id} cites unknown source {citation.doc!r}")
                # shall / note / unclassified only exist in normative documents.
                if (citation.strength in _NORMATIVE_DOC_STRENGTHS) != self.sources[citation.doc].normative:
                    raise ValueError(f"{rule.id}: strength {citation.strength!r} doesn't fit "
                                     f"source {citation.doc!r}")
            # A rule is only a spec rule if a "shall" says so; NOTEs are informative.
            if rule.kind == "normative" and not any(
                    citation.strength == "shall" for citation in rule.sources):
                raise ValueError(f"{rule.id} is normative but cites no 'shall' requirement")
        return self

    @cached_property
    def by_id(self) -> dict[str, Rule]:
        return {rule.id: rule for rule in self.rules}

    def get(self, rule_id: str) -> Rule:
        try:
            return self.by_id[rule_id]
        except KeyError:
            raise KeyError(f"no rule {rule_id!r} in the registry") from None

    def of_kind(self, *kinds: RuleKind) -> list[Rule]:
        return [rule for rule in self.rules if rule.kind in kinds]


def load_rules(path: Path = RULES_FILE) -> RuleRegistry:
    """Load and check the rule registry; raises ``pydantic.ValidationError`` if malformed."""
    with Path(path).open(encoding="utf-8") as f:
        return RuleRegistry.model_validate(yaml.safe_load(f))
