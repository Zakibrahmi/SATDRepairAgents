from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

from .prompts import EXPLORATION_SYSTEM_PROMPT, EXPLORATION_USER_PROMPT
from .schemas import RetrievedArtifact, SATDInstance


def _safe_json_loads(text: str) -> dict:
    try:
        parsed = json.loads((text or "").strip())
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


class LocalCodexExplorer:
    """
    Cost-aware repository exploration helper.

    It tries to use a local Codex CLI to summarize retrieved artifacts. If the CLI
    is not configured or fails, it falls back to a deterministic summary so the
    pipeline remains runnable.
    """

    def __init__(self, config):
        self.config = config

    def explore(
        self,
        instance: SATDInstance,
        artifacts: List[RetrievedArtifact],
        retrieved_context: str,
    ) -> Tuple[RetrievedArtifact, str]:
        if self.config.use_local_codex_for_exploration and self.config.codex_cli_command:
            cli_summary = self._run_local_codex(instance, retrieved_context)
            if cli_summary:
                return (
                    RetrievedArtifact(
                        artifact_type="repo_exploration",
                        title="Local Codex exploration summary",
                        location=f"{instance.repo_slug}:{instance.url_file_path}",
                        content=cli_summary,
                        score=0.9,
                        metadata={"backend": "local_codex_cli"},
                    ),
                    "local_codex_cli",
                )

        fallback_summary = self._fallback_summary(artifacts)
        return (
            RetrievedArtifact(
                artifact_type="repo_exploration",
                title="Heuristic repository exploration summary",
                location=f"{instance.repo_slug}:{instance.url_file_path}",
                content=fallback_summary,
                score=0.4,
                metadata={"backend": "fallback_summary"},
            ),
            "fallback_summary",
        )

    def _run_local_codex(self, instance: SATDInstance, retrieved_context: str) -> str:
        with tempfile.TemporaryDirectory(prefix="satd_codex_explore_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            system_path = tmp_path / "system_prompt.txt"
            user_path = tmp_path / "user_prompt.txt"

            system_path.write_text(EXPLORATION_SYSTEM_PROMPT, encoding="utf-8")
            user_path.write_text(
                EXPLORATION_USER_PROMPT.format(
                    comment=instance.comment,
                    repo_slug=instance.repo_slug,
                    file_path=instance.url_file_path,
                    line_number=instance.url_line_start,
                    retrieved_context=retrieved_context[:16000],
                ),
                encoding="utf-8",
            )

            command = self.config.codex_cli_command.format(
                system_prompt_file=str(system_path),
                user_prompt_file=str(user_path),
            )

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.config.codex_cli_timeout_seconds,
                    shell=True,
                    check=False,
                )
            except Exception:
                return ""

            if result.returncode != 0:
                return ""

            payload = _safe_json_loads(result.stdout)
            return self._normalize_cli_payload(payload)

    def _normalize_cli_payload(self, payload: dict) -> str:
        if not payload:
            return ""

        if payload.get("summary"):
            return str(payload.get("summary", "")).strip()

        parts = []
        for key in [
            "service_context",
            "relevant_files",
            "dependency_notes",
            "test_notes",
            "commit_notes",
            "exploration_notes",
        ]:
            value = payload.get(key)
            if not value:
                continue
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value if str(v).strip())
            parts.append(f"{key}: {value}")
        return "\n".join(parts).strip()

    def _fallback_summary(self, artifacts: List[RetrievedArtifact]) -> str:
        grouped = {}
        for artifact in artifacts:
            grouped.setdefault(artifact.artifact_type, []).append(artifact)

        lines = ["Repository exploration fallback summary:"]
        for artifact_type in sorted(grouped):
            sample_locations = [a.location for a in grouped[artifact_type][:3]]
            lines.append(
                f"- {artifact_type}: {len(grouped[artifact_type])} artifact(s); examples: "
                + ", ".join(sample_locations)
            )
        return "\n".join(lines)
