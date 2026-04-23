from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def run_git(repo_path: Path, args: List[str], check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Git failed: git -C {repo_path} {' '.join(args)}\n{result.stderr}")
    return result.stdout


def repo_slug_to_local_dir(repos_dir: Path, repo_slug: str, use_double_underscore_repo_dir: bool = True) -> Path:
    return repos_dir / (repo_slug.replace("/", "__") if use_double_underscore_repo_dir else repo_slug)


def ensure_local_repo_exists(repos_dir: Path, repo_slug: str, use_double_underscore_repo_dir: bool = True) -> Path:
    repo_path = repo_slug_to_local_dir(repos_dir, repo_slug, use_double_underscore_repo_dir)
    if not repo_path.exists():
        raise FileNotFoundError(f"Local repo not found for '{repo_slug}'. Expected at: {repo_path}")
    if not (repo_path / ".git").exists():
        raise FileNotFoundError(f"Folder exists but is not a git repository: {repo_path}")
    return repo_path


def git_show_file_at_commit(repo_path: Path, commit_sha: str, file_path: str) -> Optional[str]:
    try:
        return run_git(repo_path, ["show", f"{commit_sha}:{file_path}"], check=True)
    except Exception:
        return None


def extract_local_context_from_text(file_text: Optional[str], line_number: int, before: int, after: int) -> str:
    if file_text is None:
        return "[FILE NOT FOUND AT SPECIFIED COMMIT]"

    lines = file_text.splitlines()
    if not lines:
        return "[EMPTY FILE]"

    idx = max(0, int(line_number) - 1)
    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)

    out = []
    for i in range(start, end):
        marker = ">>" if (i + 1) == int(line_number) else "  "
        out.append(f"{marker} {i + 1:5d}: {lines[i]}")
    return "\n".join(out)


def git_recent_file_commits(repo_path: Path, file_path: str, limit: int = 5) -> List[str]:
    out = run_git(repo_path, ["log", f"-n{limit}", "--format=%H|%ci|%s", "--", file_path], check=False)
    return [line.strip() for line in out.splitlines() if line.strip()]


def git_grep(repo_path: Path, pattern: str, max_hits: int = 10) -> List[str]:
    out = run_git(repo_path, ["grep", "-n", "-I", "-i", pattern], check=False)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[:max_hits]

