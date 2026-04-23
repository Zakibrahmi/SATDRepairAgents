from __future__ import annotations

import json
from typing import Dict, List

from .explorer import LocalCodexExplorer
from .llm import SATDAgentLLM
from .prompts import (
    PATCH_SYSTEM_PROMPT,
    PATCH_USER_PROMPT,
    PLANNING_SYSTEM_PROMPT,
    PLANNING_USER_PROMPT,
    UNDERSTANDING_SYSTEM_PROMPT,
    UNDERSTANDING_USER_PROMPT,
    VALIDATION_SYSTEM_PROMPT,
    VALIDATION_USER_PROMPT,
)
from .retrieval import HybridContextRetriever
from .schemas import (
    AgentRunResult,
    FixPlanOutput,
    PatchOutput,
    RetrievedArtifact,
    SATDInstance,
    UnderstandingOutput,
    ValidationOutput,
)


def _json_dump(data: Dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _safe_confidence(value, default: float = 0.0) -> float:
    try:
        score = float(value)
    except Exception:
        return default
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


class SATDAgentPipeline:
    """
    Simple SATD-Agent pipeline with explicit staged orchestration:
    1. Context retrieval
    2. Repository exploration
    3. SATD understanding
    4. Fix planning
    5. Patch generation
    6. Validation

    LangGraph is preferred conceptually for orchestration, but a sequential fallback keeps
    the implementation simple and runnable even when LangGraph is unavailable.
    """

    def __init__(self, config):
        self.config = config
        self.llm = SATDAgentLLM(config)
        self.retriever = HybridContextRetriever(config)
        self.explorer = LocalCodexExplorer(config)

    def run(self, instance: SATDInstance, model_name: str) -> AgentRunResult:
        trace: List[Dict] = []
        try:
            generator_model = model_name
            judge_model = self.config.model_for_stage("validation")
            artifacts = self.retriever.retrieve(instance)
            retrieved_context = self.retriever.summarize(artifacts)
            trace.append(
                {
                    "step": "context_retrieval",
                    "agent": "retrieval_layer",
                    "model": "non_llm",
                    "artifact_count": len(artifacts),
                    "artifact_types": sorted({a.artifact_type for a in artifacts}),
                }
            )

            exploration_artifact, exploration_backend = self.explorer.explore(
                instance,
                artifacts,
                retrieved_context,
            )
            artifacts.append(exploration_artifact)
            augmented_context = (
                retrieved_context
                + "\n\n"
                + f"[repo_exploration] {exploration_artifact.title} @ {exploration_artifact.location}\n"
                + exploration_artifact.content
            )
            trace.append(
                {
                    "step": "repo_exploration",
                    "agent": "explorer_agent",
                    "model": exploration_backend,
                    "output": {
                        "title": exploration_artifact.title,
                        "location": exploration_artifact.location,
                        "backend": exploration_backend,
                    },
                }
            )

            understanding = self._understand(instance, artifacts, generator_model)
            trace.append(
                {
                    "step": "satd_understanding",
                    "agent": "generator_agent",
                    "model": generator_model,
                    "output": understanding.__dict__,
                }
            )

            plan = self._plan(instance, understanding, augmented_context, generator_model)
            trace.append(
                {
                    "step": "fix_planning",
                    "agent": "generator_agent",
                    "model": generator_model,
                    "output": plan.__dict__,
                }
            )

            patch = self._generate_patch(instance, understanding, plan, augmented_context, generator_model)
            trace.append(
                {
                    "step": "patch_generation",
                    "agent": "generator_agent",
                    "model": generator_model,
                    "output": patch.__dict__,
                }
            )

            validation = self._validate(instance, patch, augmented_context, judge_model)
            trace.append(
                {
                    "step": "validation",
                    "agent": "judge_agent",
                    "model": judge_model,
                    "output": validation.__dict__,
                }
            )

            return AgentRunResult(
                url=instance.url,
                comment=instance.comment,
                status=instance.status,
                repo_slug=instance.repo_slug,
                url_revision=instance.url_revision,
                url_file_path=instance.url_file_path,
                url_line_start=instance.url_line_start,
                fix_commit=instance.fix_commit,
                fix_type=instance.fix_type,
                fix_message=instance.fix_message,
                model_name=model_name,
                generator_model_used=generator_model,
                judge_model_used=judge_model,
                processing_status="ok",
                error_message="",
                understanding_debt_summary=understanding.debt_summary,
                understanding_likely_service=understanding.likely_service,
                understanding_likely_root_cause=understanding.likely_root_cause,
                understanding_likely_fix_scope=understanding.likely_fix_scope,
                retrieved_context_summary=augmented_context[:8000],
                retrieved_artifact_count=len(artifacts),
                retrieved_artifact_types=";".join(sorted({a.artifact_type for a in artifacts})),
                agent_fix_kind=plan.fix_kind,
                agent_predicted_fix_category=plan.predicted_fix_category,
                agent_rationale=plan.rationale,
                agent_proposed_fix=patch.proposed_fix,
                agent_patch_format=patch.patch_format,
                agent_touched_files=";".join(patch.touched_files),
                validation_status=validation.validation_status,
                validation_syntactic_validity=validation.syntactic_validity,
                validation_localization_accuracy=validation.localization_accuracy,
                validation_confidence=validation.validation_confidence,
                fix_confidence=validation.fix_confidence,
                validation_notes=validation.validation_notes,
                step_trace_json=_json_dump(trace),
            )
        except Exception as exc:
            return AgentRunResult(
                url=instance.url,
                comment=instance.comment,
                status=instance.status,
                repo_slug=instance.repo_slug,
                url_revision=instance.url_revision,
                url_file_path=instance.url_file_path,
                url_line_start=instance.url_line_start,
                fix_commit=instance.fix_commit,
                fix_type=instance.fix_type,
                fix_message=instance.fix_message,
                model_name=model_name,
                generator_model_used=model_name,
                judge_model_used=self.config.model_for_stage("validation"),
                processing_status="error",
                error_message=str(exc),
                step_trace_json=_json_dump(trace),
            )

    def _understand(self, instance: SATDInstance, artifacts: List[RetrievedArtifact], model_name: str) -> UnderstandingOutput:
        local_context = ""
        exploration_summary = ""
        for artifact in artifacts:
            if artifact.artifact_type == "surrounding_code":
                local_context = artifact.content
            elif artifact.artifact_type == "repo_exploration":
                exploration_summary = artifact.content

        payload = self.llm.call_json(
            model_name=model_name,
            system_prompt=UNDERSTANDING_SYSTEM_PROMPT,
            user_prompt=UNDERSTANDING_USER_PROMPT.format(
                comment=instance.comment,
                file_path=instance.url_file_path,
                line_number=instance.url_line_start,
                local_context=local_context,
                exploration_summary=exploration_summary[:8000],
            ),
            fallback={
                "debt_summary": "",
                "likely_service": "",
                "likely_root_cause": "",
                "likely_fix_scope": "",
                "notes": "",
            },
        )
        self.llm.maybe_sleep()
        return UnderstandingOutput(
            debt_summary=payload.get("debt_summary", ""),
            likely_service=payload.get("likely_service", ""),
            likely_root_cause=payload.get("likely_root_cause", ""),
            likely_fix_scope=payload.get("likely_fix_scope", ""),
            notes=payload.get("notes", ""),
        )

    def _plan(self, instance: SATDInstance, understanding: UnderstandingOutput, retrieved_context: str, model_name: str) -> FixPlanOutput:
        payload = self.llm.call_json(
            model_name=model_name,
            system_prompt=PLANNING_SYSTEM_PROMPT,
            user_prompt=PLANNING_USER_PROMPT.format(
                understanding_json=_json_dump(understanding.__dict__),
                retrieved_context=retrieved_context[:12000],
            ),
            fallback={
                "fix_kind": "improvement",
                "predicted_fix_category": "unknown",
                "rationale": "",
                "implementation_plan": [],
            },
        )
        self.llm.maybe_sleep()
        return FixPlanOutput(
            fix_kind=payload.get("fix_kind", ""),
            predicted_fix_category=payload.get("predicted_fix_category", ""),
            rationale=payload.get("rationale", ""),
            implementation_plan=payload.get("implementation_plan", []) or [],
        )

    def _generate_patch(
        self,
        instance: SATDInstance,
        understanding: UnderstandingOutput,
        plan: FixPlanOutput,
        retrieved_context: str,
        model_name: str,
    ) -> PatchOutput:
        payload = self.llm.call_json(
            model_name=model_name,
            system_prompt=PATCH_SYSTEM_PROMPT,
            user_prompt=PATCH_USER_PROMPT.format(
                comment=instance.comment,
                understanding_json=_json_dump(understanding.__dict__),
                plan_json=_json_dump(plan.__dict__),
                retrieved_context=retrieved_context[:16000],
            ),
            fallback={
                "proposed_fix": "",
                "patch_format": "text",
                "touched_files": [],
            },
        )
        self.llm.maybe_sleep()
        return PatchOutput(
            proposed_fix=payload.get("proposed_fix", ""),
            patch_format=payload.get("patch_format", "text"),
            touched_files=payload.get("touched_files", []) or [],
        )

    def _validate(self, instance: SATDInstance, patch: PatchOutput, retrieved_context: str, model_name: str) -> ValidationOutput:
        payload = self.llm.call_json(
            model_name=model_name,
            system_prompt=VALIDATION_SYSTEM_PROMPT,
            user_prompt=VALIDATION_USER_PROMPT.format(
                comment=instance.comment,
                retrieved_context=retrieved_context[:12000],
                proposed_fix=patch.proposed_fix[:8000],
            ),
            fallback={
                "validation_status": "uncertain",
                "syntactic_validity": "unknown",
                "localization_accuracy": "low",
                "validation_confidence": 0.0,
                "fix_confidence": 0.0,
                "validation_notes": "",
            },
        )
        self.llm.maybe_sleep()
        return ValidationOutput(
            validation_status=payload.get("validation_status", "uncertain"),
            syntactic_validity=payload.get("syntactic_validity", "unknown"),
            localization_accuracy=payload.get("localization_accuracy", "low"),
            validation_confidence=_safe_confidence(payload.get("validation_confidence", 0.0)),
            fix_confidence=_safe_confidence(payload.get("fix_confidence", 0.0)),
            validation_notes=payload.get("validation_notes", ""),
        )


def build_langgraph_pipeline_if_available(config):
    """
    Optional helper that returns a compiled LangGraph if the dependency is installed.
    The actual experiment runner can still use the simpler sequential pipeline above.
    """
    try:
        from langgraph.graph import StateGraph, START, END
    except Exception:
        return None

    class State(dict):
        pass

    pipeline = SATDAgentPipeline(config)
    graph = StateGraph(State)

    def understand_node(state: State):
        understanding = pipeline._understand(state["instance"], state["artifacts"], state["model_name"])
        return {"understanding": understanding}

    def retrieve_node(state: State):
        artifacts = pipeline.retriever.retrieve(state["instance"])
        return {"artifacts": artifacts, "retrieved_context": pipeline.retriever.summarize(artifacts)}

    def explore_node(state: State):
        exploration_artifact, _ = pipeline.explorer.explore(
            state["instance"],
            state["artifacts"],
            state["retrieved_context"],
        )
        artifacts = [*state["artifacts"], exploration_artifact]
        retrieved_context = (
            state["retrieved_context"]
            + "\n\n"
            + f"[repo_exploration] {exploration_artifact.title} @ {exploration_artifact.location}\n"
            + exploration_artifact.content
        )
        return {"artifacts": artifacts, "retrieved_context": retrieved_context}

    def plan_node(state: State):
        plan = pipeline._plan(state["instance"], state["understanding"], state["retrieved_context"], state["model_name"])
        return {"plan": plan}

    def patch_node(state: State):
        patch = pipeline._generate_patch(
            state["instance"], state["understanding"], state["plan"], state["retrieved_context"], state["model_name"]
        )
        return {"patch": patch}

    def validate_node(state: State):
        validation = pipeline._validate(
            state["instance"],
            state["patch"],
            state["retrieved_context"],
            config.model_for_stage("validation"),
        )
        return {"validation": validation}

    graph.add_node("retrieve", retrieve_node)
    graph.add_node("explore", explore_node)
    graph.add_node("understand", understand_node)
    graph.add_node("plan", plan_node)
    graph.add_node("patch", patch_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "explore")
    graph.add_edge("explore", "understand")
    graph.add_edge("understand", "plan")
    graph.add_edge("plan", "patch")
    graph.add_edge("patch", "validate")
    graph.add_edge("validate", END)
    return graph.compile()
