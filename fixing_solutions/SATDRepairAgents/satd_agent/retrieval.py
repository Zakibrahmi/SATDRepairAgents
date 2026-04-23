from __future__ import annotations

from pathlib import Path
from typing import List

from .git_tools import (
    ensure_local_repo_exists,
    extract_local_context_from_text,
    git_grep,
    git_recent_file_commits,
    git_show_file_at_commit,
)
from .github_context import GitHubDiscussionRetriever
from .schemas import RetrievedArtifact, SATDInstance


DEPENDENCY_FILE_NAMES = [
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "pom.xml",
    "go.mod",
    "Cargo.toml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
]


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


class HybridContextRetriever:
    """
    Simple hybrid retriever:
    - always uses local repo artifacts from cloned repositories
    - optionally enriches results with GitHub issue/PR discussions
    - optionally supports Qdrant if configured later
    """

    def __init__(self, config):
        self.config = config
        self.github_retriever = GitHubDiscussionRetriever(config)

    def retrieve(self, instance: SATDInstance) -> List[RetrievedArtifact]:
        repo_path = ensure_local_repo_exists(
            self.config.repos_dir,
            instance.repo_slug,
            self.config.use_double_underscore_repo_dir,
        )

        artifacts: List[RetrievedArtifact] = []
        artifacts.extend(self._surrounding_code(repo_path, instance))
        artifacts.extend(self._commit_history(repo_path, instance))
        artifacts.extend(self._dependency_files(repo_path, instance))
        artifacts.extend(self._test_files(repo_path, instance))
        artifacts.extend(self._lexical_related_files(repo_path, instance))
        artifacts.extend(self.github_retriever.retrieve(instance))
        return artifacts

    def _surrounding_code(self, repo_path: Path, instance: SATDInstance) -> List[RetrievedArtifact]:
        file_text = git_show_file_at_commit(repo_path, instance.url_revision, instance.url_file_path)
        context = extract_local_context_from_text(
            file_text,
            instance.url_line_start,
            before=self.config.local_context_before,
            after=self.config.local_context_after,
        )
        return [
            RetrievedArtifact(
                artifact_type="surrounding_code",
                title=f"Local context for {instance.url_file_path}",
                location=f"{instance.url_revision}:{instance.url_file_path}:{instance.url_line_start}",
                content=context,
                score=1.0,
            )
        ]

    def _commit_history(self, repo_path: Path, instance: SATDInstance) -> List[RetrievedArtifact]:
        commits = git_recent_file_commits(repo_path, instance.url_file_path, limit=self.config.max_related_commits)
        if not commits:
            return []
        return [
            RetrievedArtifact(
                artifact_type="commit_history",
                title=f"Recent commits for {instance.url_file_path}",
                location=instance.url_file_path,
                content="\n".join(commits),
                score=0.8,
            )
        ]

    def _dependency_files(self, repo_path: Path, instance: SATDInstance) -> List[RetrievedArtifact]:
        artifacts: List[RetrievedArtifact] = []
        service_root = repo_path / Path(instance.url_file_path).parent
        parents = [service_root, *service_root.parents]
        seen = set()

        for parent in parents:
            if str(parent) == str(repo_path.parent):
                break
            for name in DEPENDENCY_FILE_NAMES:
                candidate = parent / name
                if candidate.exists() and candidate not in seen:
                    seen.add(candidate)
                    artifacts.append(
                        RetrievedArtifact(
                            artifact_type="dependency_file",
                            title=name,
                            location=str(candidate),
                            content=_safe_read_text(candidate)[:4000],
                            score=0.6,
                        )
                    )
                    if len(artifacts) >= self.config.max_dependency_files:
                        return artifacts
        return artifacts

    def _test_files(self, repo_path: Path, instance: SATDInstance) -> List[RetrievedArtifact]:
        artifacts: List[RetrievedArtifact] = []
        target = Path(instance.url_file_path)
        stem = target.stem
        candidates = [
            repo_path / "tests",
            repo_path / target.parent,
        ]
        seen = set()
        for base in candidates:
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path in seen:
                    continue
                lower = path.name.lower()
                if stem.lower() in lower and ("test" in lower or "spec" in lower):
                    seen.add(path)
                    artifacts.append(
                        RetrievedArtifact(
                            artifact_type="test_file",
                            title=path.name,
                            location=str(path),
                            content=_safe_read_text(path)[:4000],
                            score=0.7,
                        )
                    )
                    if len(artifacts) >= self.config.max_test_files:
                        return artifacts
        return artifacts

    def _lexical_related_files(self, repo_path: Path, instance: SATDInstance) -> List[RetrievedArtifact]:
        artifacts: List[RetrievedArtifact] = []
        comment_tokens = [token for token in instance.comment.split() if len(token) > 4][:3]
        for token in comment_tokens:
            hits = git_grep(repo_path, token, max_hits=self.config.max_search_hits)
            for hit in hits:
                file_part = hit.split(":", 2)[0] if ":" in hit else hit
                artifacts.append(
                    RetrievedArtifact(
                        artifact_type="lexical_search_hit",
                        title=f"Search hit for '{token}'",
                        location=file_part,
                        content=hit[:1000],
                        score=0.5,
                    )
                )
                if len(artifacts) >= self.config.max_search_hits:
                    return artifacts
        return artifacts

    def summarize(self, artifacts: List[RetrievedArtifact]) -> str:
        lines = []
        for artifact in artifacts:
            lines.append(
                f"[{artifact.artifact_type}] {artifact.title} @ {artifact.location}\n{artifact.content[:1200]}"
            )
        return "\n\n".join(lines)

