from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


@dataclass
class SATDInstance:
    """One SATD sample from the Excel dataset."""

    url: str
    comment: str
    status: str
    repo_slug: str
    url_revision: str
    url_file_path: str
    url_line_start: int
    fix_commit: str = ""
    fix_type: str = ""
    fix_message: str = ""


@dataclass
class RetrievedArtifact:
    """A retrieved artifact used as agent context."""

    artifact_type: str
    title: str
    location: str
    content: str
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UnderstandingOutput:
    debt_summary: str = ""
    likely_service: str = ""
    likely_root_cause: str = ""
    likely_fix_scope: str = ""
    notes: str = ""


@dataclass
class FixPlanOutput:
    fix_kind: str = ""
    predicted_fix_category: str = ""
    rationale: str = ""
    implementation_plan: List[str] = field(default_factory=list)


@dataclass
class PatchOutput:
    proposed_fix: str = ""
    patch_format: str = "text"
    touched_files: List[str] = field(default_factory=list)


@dataclass
class ValidationOutput:
    validation_status: str = ""
    syntactic_validity: str = ""
    localization_accuracy: str = ""
    validation_confidence: float = 0.0
    fix_confidence: float = 0.0
    validation_notes: str = ""


@dataclass
class AgentRunResult:
    """Final evaluation-friendly record written to Excel."""

    url: str
    comment: str
    status: str
    repo_slug: str
    url_revision: str
    url_file_path: str
    url_line_start: int
    fix_commit: str
    fix_type: str
    fix_message: str
    model_name: str
    processing_status: str
    error_message: str
    generator_model_used: str = ""
    judge_model_used: str = ""

    understanding_debt_summary: str = ""
    understanding_likely_service: str = ""
    understanding_likely_root_cause: str = ""
    understanding_likely_fix_scope: str = ""

    retrieved_context_summary: str = ""
    retrieved_artifact_count: int = 0
    retrieved_artifact_types: str = ""

    agent_fix_kind: str = ""
    agent_predicted_fix_category: str = ""
    agent_rationale: str = ""
    agent_proposed_fix: str = ""
    agent_patch_format: str = ""
    agent_touched_files: str = ""

    validation_status: str = ""
    validation_syntactic_validity: str = ""
    validation_localization_accuracy: str = ""
    validation_confidence: float = 0.0
    fix_confidence: float = 0.0
    validation_notes: str = ""

    step_trace_json: str = ""

    def to_flat_dict(self) -> Dict[str, Any]:
        return asdict(self)
