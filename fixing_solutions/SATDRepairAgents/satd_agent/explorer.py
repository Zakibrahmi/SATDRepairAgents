from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

from .prompts import EXPLORATION_SYSTEM_PROMPT, EXPLORATION_USER_PROMPT
from .schemas import RetrievedArtifact, SATDInstance


def _safe_json_loads(text: str) -> dict:
    try:
        parsed = json.loads((text or "").strip())
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _shell_quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


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
        if self.config.use_local_codex_for_exploration:
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
        repo_dir = self._repo_dir_for_instance(instance)
        tmp_root = Path.cwd() / ".satd_codex_tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_root / f"satd_codex_explore_{uuid4().hex}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        try:
            system_path = tmp_path / "system_prompt.txt"
            user_path = tmp_path / "user_prompt.txt"
            combined_path = tmp_path / "combined_prompt.txt"

            system_path.write_text(EXPLORATION_SYSTEM_PROMPT, encoding="utf-8")
            user_prompt = EXPLORATION_USER_PROMPT.format(
                comment=instance.comment,
                repo_slug=instance.repo_slug,
                repo_dir=str(repo_dir),
                file_path=instance.url_file_path,
                line_number=instance.url_line_start,
                retrieved_context=retrieved_context[:16000],
            )
            user_path.write_text(user_prompt, encoding="utf-8")
            combined_path.write_text(
                EXPLORATION_SYSTEM_PROMPT.strip()
                + "\n\n"
                + user_prompt.strip()
                + "\n",
                encoding="utf-8",
            )

            command_template = self.config.codex_cli_command or self._default_codex_command_template()
            command = self._render_command_template(
                command_template,
                system_prompt_file=str(system_path),
                user_prompt_file=str(user_path),
                combined_prompt_file=str(combined_path),
                repo_dir=str(repo_dir),
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

            return self._normalize_cli_stdout(result.stdout)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def _repo_dir_for_instance(self, instance: SATDInstance) -> Path:
        repo_name = instance.repo_slug.replace("/", "__") if self.config.use_double_underscore_repo_dir else instance.repo_slug
        return self.config.repos_dir / repo_name

    def _default_codex_command_template(self) -> str:
        return (
            f"Get-Content -Raw {_shell_quote('{combined_prompt_file}')} | "
            f"codex exec --json --skip-git-repo-check --cwd {_shell_quote('{repo_dir}')} -"
        )

    def _render_command_template(self, command_template: str, **values: str) -> str:
        command = str(command_template)
        for key, value in values.items():
            command = command.replace("{" + key + "}", value)
        return command

    def _normalize_cli_stdout(self, stdout: str) -> str:
        stdout = (stdout or "").strip()
        if not stdout:
            return ""

        payload = _safe_json_loads(stdout)
        if payload:
            text = self._extract_text_from_event(payload)
            if text:
                return text
            return self._normalize_cli_payload(payload)

        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        for line in reversed(lines):
            payload = _safe_json_loads(line)
            if not payload:
                continue

            text = self._extract_text_from_event(payload)
            if text:
                return text

            normalized = self._normalize_cli_payload(payload)
            if normalized:
                return normalized
        return ""

    def _extract_text_from_event(self, event: dict) -> str:
        event_type = str(event.get("type", "")).strip()
        payload = event.get("payload")

        if event_type == "agent_message" and isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()

        if event_type == "response_item" and isinstance(payload, dict):
            item = payload.get("payload")
            if isinstance(item, dict):
                if item.get("type") == "message":
                    content = item.get("content") or []
                    parts = []
                    for chunk in content:
                        if not isinstance(chunk, dict):
                            continue
                        text = chunk.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
                    if parts:
                        return "\n".join(parts).strip()
        return ""

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
