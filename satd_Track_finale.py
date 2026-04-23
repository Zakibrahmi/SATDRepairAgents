import os
import re
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from difflib import SequenceMatcher
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from utils import llm_judge_retained_resolution


# =========================================================
# Configuration
# =========================================================
INPUT_EXCEL = "./data/SATD_2years.xlsx"
OUTPUT_EXCEL = "./results/satd_fix_detection_2years.xlsx"
REPOS_DIR = Path(r"C:/satd_microservice/repos/clones")

COL_COMMENT = "comment"
COL_URL = "url"

SIMILARITY_THRESHOLD = 0.72
STRONG_LINE_MATCH_THRESHOLD = 0.88

MIN_CODE_CHANGE_RATIO = 0.15
MIN_ABSOLUTE_CODE_CHANGES = 3
MAX_FILES_CHANGED_FOR_LOCAL_FIX = 8

DIFF_CONTEXT_LINES = 12
LINE_WINDOW = 5
SNIPPET_RADIUS = 12
MAX_LLM_CHARS = 12000

PREFERRED_BRANCHES = [
    "main",
    "master",
    "develop",
    "dev",
    "trunk",
    "release",
]


# =========================================================
# Data structures
# =========================================================
class FixType(Enum):
    REMOVED_ONLY = "removed_only"
    RESOLVED_AND_REMOVED = "resolved_and_removed"
    FILE_DELETED = "file_deleted"
    COMMENT_MODIFIED = "comment_modified"
    RESOLVED_RETAINED = "resolved_comment_retained"
    PARTIALLY_RESOLVED_RETAINED = "partially_resolved_comment_retained"


class DetectionStatus(Enum):
    FIX_FOUND = "fix_found"
    STILL_PRESENT = "still_present"
    COMMENT_NOT_FOUND = "comment_not_found"
    INVALID_INPUT = "invalid_input"
    ERROR = "error"


@dataclass
class FixEvent:
    commit: str
    fix_type: FixType
    message: str
    date: str
    confidence: str
    details: Dict[str, Any]
    llm_label: Optional[str] = None
    llm_reason: Optional[str] = None
    code_changes_nearby: int = 0


@dataclass
class DetectionResult:
    status: DetectionStatus
    repo_slug: Optional[str] = None
    url_revision: Optional[str] = None
    url_file_path: Optional[str] = None
    url_line_start: Optional[int] = None

    matched_file: Optional[str] = None
    matched_line_number: Optional[int] = None
    matched_line_text: Optional[str] = None
    line_match_similarity: Optional[float] = None
    line_match_source: Optional[str] = None

    fix_commit: Optional[str] = None
    fix_type: Optional[str] = None
    fix_message: Optional[str] = None
    fix_date: Optional[str] = None
    heuristic_confidence: Optional[str] = None
    llm_label: Optional[str] = None
    llm_reason: Optional[str] = None

    branch_used: Optional[str] = None
    all_branches_checked: List[str] = field(default_factory=list)
    satd_introduction_commit: Optional[str] = None
    candidate_fixes: List[Dict[str, Any]] = field(default_factory=list)
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "repo_slug": self.repo_slug,
            "url_revision": self.url_revision,
            "url_file_path": self.url_file_path,
            "url_line_start": self.url_line_start,
            "matched_file": self.matched_file,
            "matched_line_number": self.matched_line_number,
            "matched_line_text": self.matched_line_text,
            "line_match_similarity": self.line_match_similarity,
            "line_match_source": self.line_match_source,
            "fix_commit": self.fix_commit,
            "fix_type": self.fix_type,
            "fix_message": self.fix_message,
            "fix_date": self.fix_date,
            "branch_used": self.branch_used,
            "satd_introduction_commit": self.satd_introduction_commit,
            "heuristic_confidence": self.heuristic_confidence,
            "llm_label": self.llm_label,
            "llm_reason": self.llm_reason,
            "candidate_fixes_count": len(self.candidate_fixes),
            "all_branches_checked": ",".join(self.all_branches_checked) if self.all_branches_checked else None,
            "details": self.details,
        }


# =========================================================
# Git helpers
# =========================================================
def run_git(repo_path: Path, args: List[str], check: bool = True) -> str:
    cmd = ["git", "-C", str(repo_path)] + args
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Git failed: {' '.join(cmd)}\nSTDERR:\n{result.stderr}")
    return result.stdout.strip()


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def clone_or_update_repo(repo_slug: str, repos_dir: Path, fetch: bool = False) -> Path:
    repos_dir.mkdir(parents=True, exist_ok=True)
    repo_name = safe_filename(repo_slug.replace("/", "__"))
    repo_path = repos_dir / repo_name

    if not repo_path.exists():
        clone_url = f"https://github.com/{repo_slug}.git"
        print(f"[CLONE] {clone_url}")
        subprocess.run(["git", "clone", "--quiet", clone_url, str(repo_path)], check=True)
    elif fetch:
        print(f"[FETCH] {repo_slug}")
        try:
            subprocess.run(
                ["git", "-C", str(repo_path), "fetch", "--all", "--quiet"],
                check=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            print(f"[WARN] Fetch timeout for {repo_slug}, using cached version")
        except Exception as e:
            print(f"[WARN] Fetch failed for {repo_slug}: {e}, using cached version")

    return repo_path


def commit_exists(repo_path: Path, commit_hash: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "cat-file", "-e", f"{commit_hash}^{{commit}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.returncode == 0


def get_parent_commit(repo_path: Path, commit_hash: str) -> Optional[str]:
    out = run_git(repo_path, ["rev-list", "--parents", "-n", "1", commit_hash], check=False)
    parts = out.split()
    return parts[1] if len(parts) >= 2 else None


def file_exists_in_commit(repo_path: Path, commit_hash: str, file_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-tree", commit_hash, file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def read_file_at_commit(repo_path: Path, commit_hash: str, file_path: str) -> Optional[str]:
    out = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{commit_hash}:{file_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout if out.returncode == 0 else None


def get_branches_containing_commit(repo_path: Path, commit_hash: str) -> List[str]:
    out = run_git(repo_path, ["branch", "-a", "--contains", commit_hash], check=False)
    branches = []
    for line in out.splitlines():
        b = line.replace("*", "").strip()
        if not b or "HEAD detached" in b:
            continue
        if b.startswith("remotes/"):
            b = b.replace("remotes/", "")
        if b.endswith("/HEAD"):
            continue
        if b not in branches:
            branches.append(b)
    return branches


def choose_branches(repo_path: Path, commit_hash: str, max_branches: int = 6) -> List[str]:
    branches = get_branches_containing_commit(repo_path, commit_hash)
    if not branches:
        return []

    selected = []

    try:
        default = run_git(repo_path, ["symbolic-ref", "refs/remotes/origin/HEAD"], check=False)
        if default:
            default_branch = default.replace("refs/remotes/origin/", "")
            for b in branches:
                if b == default_branch or b.endswith("/" + default_branch):
                    selected.append(b)
                    break
    except Exception:
        pass

    for pref in PREFERRED_BRANCHES:
        for b in branches:
            if b == pref or b.endswith("/" + pref):
                if b not in selected:
                    selected.append(b)

    for b in branches:
        if b not in selected:
            selected.append(b)
        if len(selected) >= max_branches:
            break

    return selected[:max_branches]


def get_file_history_after_commit(
    repo_path: Path,
    file_path: str,
    start_commit: str,
    branch: Optional[str] = None,
) -> List[str]:
    rev_range = f"{start_commit}..{branch}" if branch else f"{start_commit}..HEAD"
    out = run_git(
        repo_path,
        ["log", "--format=%H", "--reverse", rev_range, "--", file_path],
        check=False,
    )
    return [x.strip() for x in out.splitlines() if x.strip()]


def get_commit_message(repo_path: Path, commit_hash: str) -> str:
    return run_git(repo_path, ["log", "-n", "1", "--format=%s", commit_hash], check=False)


def get_commit_date(repo_path: Path, commit_hash: str) -> str:
    return run_git(repo_path, ["log", "-n", "1", "--format=%ci", commit_hash], check=False)


def get_commit_stats(repo_path: Path, commit_hash: str) -> Dict[str, int]:
    out = run_git(repo_path, ["show", "--shortstat", "--format=", commit_hash], check=False)
    stats = {"files_changed": 0, "insertions": 0, "deletions": 0}
    m_files = re.search(r"(\d+)\s+files? changed", out)
    m_ins = re.search(r"(\d+)\s+insertions?\(\+\)", out)
    m_del = re.search(r"(\d+)\s+deletions?\(-\)", out)
    if m_files:
        stats["files_changed"] = int(m_files.group(1))
    if m_ins:
        stats["insertions"] = int(m_ins.group(1))
    if m_del:
        stats["deletions"] = int(m_del.group(1))
    return stats


def get_diff_for_file(
    repo_path: Path,
    parent_commit: str,
    commit_hash: str,
    file_path: str,
    context_lines: int = DIFF_CONTEXT_LINES,
) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo_path), "diff", f"-U{context_lines}", parent_commit, commit_hash, "--", file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout if out.returncode == 0 else ""


# =========================================================
# Text helpers
# =========================================================
def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"^\s*(//+|#+|/\*+|\*+|--|<!--)\s*", "", text.strip())
    text = re.sub(r"\s*(\*+/|-->)\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def file_contains_comment(content: str, satd_comment: str, threshold: float = 0.75) -> bool:
    if not content:
        return False

    satd_norm = normalize_text(satd_comment)
    content_norm = normalize_text(content)

    if satd_norm in content_norm:
        return True

    lines = [normalize_text(l) for l in content.splitlines() if normalize_text(l)]
    best = 0.0
    for line in lines:
        if satd_norm in line or line in satd_norm:
            return True
        best = max(best, SequenceMatcher(None, satd_norm, line).ratio())

    return best >= threshold


def is_comment_like_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True

    markers = ("//", "#", "/*", "*", "*/", "--", "<!--", "-->", '"""', "'''", "%", ";")
    if s.startswith(markers):
        return True

    if "//" in s or "#" in s:
        for marker in ["//", "#"]:
            if marker in s:
                idx = s.index(marker)
                code_part = s[:idx].strip()
                comment_part = s[idx:].strip()
                if len(comment_part) > len(code_part):
                    return True

    return False


def extract_similar_lines(content: str, target_comment: str, top_k: int = 5):
    target = normalize_text(target_comment)
    scored = []
    for line in content.splitlines():
        norm = normalize_text(line)
        if not norm:
            continue
        score = SequenceMatcher(None, target, norm).ratio()
        scored.append((score, line.strip()))
    scored.sort(reverse=True, key=lambda x: x[0])
    return scored[:top_k]


# =========================================================
# URL parsing
# =========================================================
def parse_github_blob_url(url: str):
    parsed = urlparse(url)
    if "github.com" not in parsed.netloc.lower():
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 5 or parts[2] != "blob":
        return None

    owner = parts[0]
    repo = parts[1].replace(".git", "")
    revision = parts[3]
    file_path = "/".join(parts[4:]) if len(parts) > 4 else None

    line_start = None
    line_end = None
    fragment = parsed.fragment or ""

    m = re.match(r"L(\d+)(?:-L?(\d+))?$", fragment)
    if m:
        line_start = int(m.group(1))
        line_end = int(m.group(2)) if m.group(2) else line_start

    return {
        "repo_slug": f"{owner}/{repo}",
        "revision": revision,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
    }


# =========================================================
# Line/snippet locating
# =========================================================
def find_comment_near_line(content: str, satd_comment: str, line_number: Optional[int], window: int = LINE_WINDOW):
    if not content:
        return None

    lines = content.splitlines()
    n = len(lines)
    if n == 0:
        return None

    target_norm = normalize_text(satd_comment)

    if line_number is None:
        for idx, line in enumerate(lines, start=1):
            if target_norm in normalize_text(line):
                return {
                    "matched_line_number": idx,
                    "matched_line_text": line.strip(),
                    "similarity": 1.0,
                    "match_type": "full_file_exact",
                }
        return None

    start = max(1, line_number - window)
    end = min(n, line_number + window)
    best = None

    for idx in range(start, end + 1):
        line = lines[idx - 1]
        line_norm = normalize_text(line)

        if target_norm in line_norm:
            return {
                "matched_line_number": idx,
                "matched_line_text": line.strip(),
                "similarity": 1.0,
                "match_type": "near_line_exact",
            }

        sim = text_similarity(line, satd_comment)
        if best is None or sim > best["similarity"]:
            best = {
                "matched_line_number": idx,
                "matched_line_text": line.strip(),
                "similarity": sim,
                "match_type": "near_line_similar",
            }

    if best and best["similarity"] >= STRONG_LINE_MATCH_THRESHOLD:
        return best

    return None


def get_snippet_around_line(content: str, line_number: Optional[int], radius: int = SNIPPET_RADIUS) -> str:
    if not content:
        return ""
    lines = content.splitlines()
    if not lines:
        return ""
    if line_number is None or line_number < 1:
        line_number = 1
    start = max(1, line_number - radius)
    end = min(len(lines), line_number + radius)
    numbered = []
    for i in range(start, end + 1):
        numbered.append(f"{i:>5}: {lines[i - 1]}")
    return "\n".join(numbered)


# =========================================================
# Commit message analysis
# =========================================================
def analyze_commit_message_context(message: str, stats: Dict[str, int]) -> Dict[str, Any]:
    msg = (message or "").lower()

    refactor_patterns = [
        r"\b(refactor|cleanup|clean up|restructure|reorganize|simplify)\b",
        r"\b(extract|remove workaround|eliminate hack)\b",
    ]
    bugfix_patterns = [r"\b(fix|bug|issue|resolve|correct|repair|hotfix)\b"]
    satd_patterns = [
        r"\b(todo|hack|temporary|workaround|debt|technical debt)\b",
        r"\b(remove todo|fix hack|resolve workaround)\b",
    ]

    is_refactoring = any(re.search(p, msg) for p in refactor_patterns)
    is_bugfix = any(re.search(p, msg) for p in bugfix_patterns)
    mentions_satd_terms = any(re.search(p, msg) for p in satd_patterns)

    score = 0
    if is_refactoring:
        score += 2
    if is_bugfix:
        score += 2
    if mentions_satd_terms:
        score += 3
    if stats.get("files_changed", 0) <= MAX_FILES_CHANGED_FOR_LOCAL_FIX:
        score += 1
    if stats.get("insertions", 0) + stats.get("deletions", 0) > 0:
        score += 1

    if score >= 6:
        msg_conf = "high"
    elif score >= 4:
        msg_conf = "medium"
    else:
        msg_conf = "low"

    return {
        "is_refactoring": is_refactoring,
        "is_bugfix": is_bugfix,
        "mentions_satd_terms": mentions_satd_terms,
        "message_confidence": msg_conf,
        "score": score,
    }


# =========================================================
# Diff analysis
# =========================================================
def deleted_line_matches_satd(line: str, satd_comment: str) -> bool:
    if not line.startswith("-") or line.startswith("---"):
        return False

    deleted_text = line[1:].strip()
    target = normalize_text(satd_comment)
    deleted_norm = normalize_text(deleted_text)

    if target in deleted_norm:
        return True

    return text_similarity(deleted_norm, target) >= STRONG_LINE_MATCH_THRESHOLD


def count_context_lines(diff_text: str) -> int:
    count = 0
    for line in diff_text.splitlines():
        if not (line.startswith("+++") or line.startswith("---") or line.startswith("@@") or line.startswith("diff")):
            count += 1
    return count


def analyze_diff_for_satd_removal(diff_text: str, satd_comment: str) -> Dict[str, Any]:
    lines = diff_text.splitlines()
    satd_deleted_indexes = []

    for i, line in enumerate(lines):
        if deleted_line_matches_satd(line, satd_comment):
            satd_deleted_indexes.append(i)

    if not satd_deleted_indexes:
        return {
            "satd_deleted": False,
            "non_comment_added": 0,
            "non_comment_deleted": 0,
            "total_code_changes": 0,
            "code_change_ratio": 0.0,
            "likely_resolved": False,
        }

    changed_line_indices = set()
    for satd_idx in satd_deleted_indexes:
        start = max(0, satd_idx - DIFF_CONTEXT_LINES)
        end = min(len(lines), satd_idx + DIFF_CONTEXT_LINES + 1)
        for j in range(start, end):
            line = lines[j]
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("+") or line.startswith("-"):
                changed_line_indices.add(j)

    non_comment_added = 0
    non_comment_deleted = 0
    for idx in changed_line_indices:
        line = lines[idx]
        if line.startswith("+"):
            body = line[1:].strip()
            if body and not is_comment_like_line(body):
                non_comment_added += 1
        elif line.startswith("-"):
            body = line[1:].strip()
            if body and not is_comment_like_line(body) and not deleted_line_matches_satd(line, satd_comment):
                non_comment_deleted += 1

    total_code_changes = non_comment_added + non_comment_deleted
    total_context = count_context_lines(diff_text)
    code_change_ratio = total_code_changes / total_context if total_context > 0 else 0.0
    likely_resolved = (
        total_code_changes >= MIN_ABSOLUTE_CODE_CHANGES and
        code_change_ratio >= MIN_CODE_CHANGE_RATIO
    )

    return {
        "satd_deleted": True,
        "non_comment_added": non_comment_added,
        "non_comment_deleted": non_comment_deleted,
        "total_code_changes": total_code_changes,
        "code_change_ratio": round(code_change_ratio, 3),
        "likely_resolved": likely_resolved,
    }


# =========================================================
# Main detection logic
# =========================================================
def detect_satd_fix_commit(
    repo_path: Path,
    satd_commit: str,
    satd_comment: str,
    file_path: str,
    satd_line_number: Optional[int] = None,
) -> DetectionResult:
    baseline_commit = satd_commit
    baseline_content = read_file_at_commit(repo_path, baseline_commit, file_path)

    if not baseline_content or not file_contains_comment(baseline_content, satd_comment):
        parent = get_parent_commit(repo_path, baseline_commit)
        if parent:
            parent_content = read_file_at_commit(repo_path, parent, file_path)
            if parent_content and file_contains_comment(parent_content, satd_comment):
                baseline_content = parent_content
            else:
                return DetectionResult(
                    status=DetectionStatus.COMMENT_NOT_FOUND,
                    details="SATD comment not found at observed commit or its parent.",
                )
        else:
            return DetectionResult(
                status=DetectionStatus.COMMENT_NOT_FOUND,
                details="SATD comment not found at observed commit.",
            )

    branches_to_check = choose_branches(repo_path, baseline_commit, max_branches=6)

    if not branches_to_check:
        return DetectionResult(
            status=DetectionStatus.ERROR,
            details="No recommended branches found containing the observed commit.",
        )

    all_candidate_fixes: List[FixEvent] = []
    earliest_definitive_fix: Optional[FixEvent] = None
    primary_branch_used = branches_to_check[0]

    for branch in branches_to_check:
        history = get_file_history_after_commit(repo_path, file_path, baseline_commit, branch)
        prev_commit = baseline_commit
        prev_content = baseline_content

        for curr_commit in history:
            curr_exists = file_exists_in_commit(repo_path, curr_commit, file_path)
            curr_content = read_file_at_commit(repo_path, curr_commit, file_path) if curr_exists else None

            prev_has = file_contains_comment(prev_content or "", satd_comment)
            curr_has = file_contains_comment(curr_content or "", satd_comment)

            fix_event = None

            if prev_has and not curr_exists:
                fix_event = FixEvent(
                    commit=curr_commit,
                    fix_type=FixType.FILE_DELETED,
                    message=get_commit_message(repo_path, curr_commit),
                    date=get_commit_date(repo_path, curr_commit),
                    confidence="high",
                    details={"reason": "file no longer exists", "branch": branch},
                )

            elif prev_has and not curr_has:
                diff_text = get_diff_for_file(repo_path, prev_commit, curr_commit, file_path)
                deletion_info = analyze_diff_for_satd_removal(diff_text, satd_comment)

                if deletion_info["satd_deleted"]:
                    fix_type = FixType.RESOLVED_AND_REMOVED if deletion_info["likely_resolved"] else FixType.REMOVED_ONLY
                    confidence = "high" if deletion_info["likely_resolved"] else "medium"

                    fix_event = FixEvent(
                        commit=curr_commit,
                        fix_type=fix_type,
                        message=get_commit_message(repo_path, curr_commit),
                        date=get_commit_date(repo_path, curr_commit),
                        confidence=confidence,
                        details={**deletion_info, "branch": branch},
                        code_changes_nearby=deletion_info["total_code_changes"],
                    )
                else:
                    similar_lines = extract_similar_lines(curr_content or "", satd_comment, top_k=3)
                    best_score = similar_lines[0][0] if similar_lines else 0.0
                    best_line = similar_lines[0][1] if similar_lines else ""
                    if best_score >= SIMILARITY_THRESHOLD:
                        fix_event = FixEvent(
                            commit=curr_commit,
                            fix_type=FixType.COMMENT_MODIFIED,
                            message=get_commit_message(repo_path, curr_commit),
                            date=get_commit_date(repo_path, curr_commit),
                            confidence="medium",
                            details={
                                "best_similarity": round(best_score, 3),
                                "new_comment": best_line,
                                "branch": branch,
                            },
                        )

            elif prev_has and curr_has:
                diff_text = get_diff_for_file(repo_path, prev_commit, curr_commit, file_path)

                non_comment_added = 0
                non_comment_deleted = 0
                for line in diff_text.splitlines():
                    if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                        continue
                    if line.startswith("+"):
                        body = line[1:].strip()
                        if body and not is_comment_like_line(body):
                            non_comment_added += 1
                    elif line.startswith("-"):
                        body = line[1:].strip()
                        if body and not is_comment_like_line(body):
                            non_comment_deleted += 1

                total_code_changes = non_comment_added + non_comment_deleted
                total_context = count_context_lines(diff_text)
                code_change_ratio = total_code_changes / total_context if total_context > 0 else 0.0

                if total_code_changes >= MIN_ABSOLUTE_CODE_CHANGES and code_change_ratio >= MIN_CODE_CHANGE_RATIO:
                    commit_message = get_commit_message(repo_path, curr_commit)
                    stats = get_commit_stats(repo_path, curr_commit)
                    msg_ctx = analyze_commit_message_context(commit_message, stats)

                    if stats.get("files_changed", 0) <= MAX_FILES_CHANGED_FOR_LOCAL_FIX and msg_ctx["score"] >= 3:
                        prev_snippet = get_snippet_around_line(prev_content, satd_line_number, SNIPPET_RADIUS)
                        curr_snippet = get_snippet_around_line(curr_content, satd_line_number, SNIPPET_RADIUS)

                        try:
                            llm_result = llm_judge_retained_resolution(
                                satd_comment=satd_comment,
                                commit_message=commit_message,
                                before_snippet=prev_snippet,
                                after_snippet=curr_snippet,
                                diff_excerpt=diff_text[:MAX_LLM_CHARS],
                            )
                            if llm_result["label"] in {"resolved", "partially_resolved"}:
                                fix_type = (
                                    FixType.RESOLVED_RETAINED
                                    if llm_result["label"] == "resolved"
                                    else FixType.PARTIALLY_RESOLVED_RETAINED
                                )
                                heuristic_conf = "high" if msg_ctx["score"] >= 6 else "medium"
                                fix_event = FixEvent(
                                    commit=curr_commit,
                                    fix_type=fix_type,
                                    message=commit_message,
                                    date=get_commit_date(repo_path, curr_commit),
                                    confidence=heuristic_conf,
                                    details={
                                        "code_changes": total_code_changes,
                                        "code_change_ratio": round(code_change_ratio, 3),
                                        "commit_message_context": msg_ctx,
                                        "branch": branch,
                                    },
                                    llm_label=llm_result["label"],
                                    llm_reason=llm_result["reason"],
                                    code_changes_nearby=total_code_changes,
                                )
                        except Exception as e:
                            print(f"[WARN] LLM judge failed for {curr_commit}: {e}")

            if fix_event:
                all_candidate_fixes.append(fix_event)
                if fix_event.fix_type in {
                    FixType.REMOVED_ONLY,
                    FixType.RESOLVED_AND_REMOVED,
                    FixType.FILE_DELETED,
                    FixType.COMMENT_MODIFIED,
                } and earliest_definitive_fix is None:
                    earliest_definitive_fix = fix_event

            prev_commit = curr_commit
            prev_content = curr_content if curr_exists else None

    if earliest_definitive_fix:
        return DetectionResult(
            status=DetectionStatus.FIX_FOUND,
            fix_commit=earliest_definitive_fix.commit,
            fix_type=earliest_definitive_fix.fix_type.value,
            fix_message=earliest_definitive_fix.message,
            fix_date=earliest_definitive_fix.date,
            heuristic_confidence=earliest_definitive_fix.confidence,
            llm_label=earliest_definitive_fix.llm_label,
            llm_reason=earliest_definitive_fix.llm_reason,
            branch_used=primary_branch_used,
            all_branches_checked=branches_to_check,
            candidate_fixes=[
                {
                    "commit": f.commit,
                    "type": f.fix_type.value,
                    "confidence": f.confidence,
                    "code_changes": f.code_changes_nearby,
                }
                for f in all_candidate_fixes
            ],
            details=json.dumps(earliest_definitive_fix.details, ensure_ascii=False),
        )

    if all_candidate_fixes:
        first_fix = all_candidate_fixes[0]
        return DetectionResult(
            status=DetectionStatus.FIX_FOUND,
            fix_commit=first_fix.commit,
            fix_type=first_fix.fix_type.value,
            fix_message=first_fix.message,
            fix_date=first_fix.date,
            heuristic_confidence=first_fix.confidence,
            llm_label=first_fix.llm_label,
            llm_reason=first_fix.llm_reason,
            branch_used=primary_branch_used,
            all_branches_checked=branches_to_check,
            candidate_fixes=[
                {
                    "commit": f.commit,
                    "type": f.fix_type.value,
                    "confidence": f.confidence,
                    "code_changes": f.code_changes_nearby,
                }
                for f in all_candidate_fixes
            ],
            details=json.dumps(first_fix.details, ensure_ascii=False),
        )

    return DetectionResult(
        status=DetectionStatus.STILL_PRESENT,
        branch_used=primary_branch_used,
        all_branches_checked=branches_to_check,
        details="No fix detected after the observed blob commit on recommended branches.",
    )


# =========================================================
# Row processing
# =========================================================
def process_row(row, repos_dir: Path, fetch_repos: bool = False) -> Dict[str, Any]:
    satd_comment = str(row[COL_COMMENT]).strip()
    url = str(row[COL_URL]).strip()

    if not satd_comment or not url:
        return DetectionResult(
            status=DetectionStatus.INVALID_INPUT,
            details="Missing comment or url",
        ).to_dict()

    try:
        url_info = parse_github_blob_url(url)

        if not url_info or not url_info.get("revision"):
            return DetectionResult(
                status=DetectionStatus.INVALID_INPUT,
                details="Could not extract commit hash from GitHub URL",
            ).to_dict()

        commit_hash = str(url_info["revision"]).strip()
        repo_slug = url_info["repo_slug"]
        url_file_path = url_info.get("file_path")
        url_line_start = url_info.get("line_start")

        if not url_file_path:
            return DetectionResult(
                status=DetectionStatus.INVALID_INPUT,
                details="GitHub URL does not contain a file path",
            ).to_dict()

        repo_path = clone_or_update_repo(repo_slug, repos_dir, fetch=fetch_repos)

        if not commit_exists(repo_path, commit_hash):
            return DetectionResult(
                status=DetectionStatus.COMMENT_NOT_FOUND,
                repo_slug=repo_slug,
                details=f"Commit {commit_hash} not found",
            ).to_dict()

        file_path = url_file_path
        located = None

        content = read_file_at_commit(repo_path, commit_hash, file_path)
        if content:
            located = find_comment_near_line(content, satd_comment, url_line_start, LINE_WINDOW)
            if located:
                located["source"] = "url_file_at_commit"

        if not located:
            parent = get_parent_commit(repo_path, commit_hash)
            if parent:
                parent_content = read_file_at_commit(repo_path, parent, file_path)
                if parent_content:
                    located = find_comment_near_line(parent_content, satd_comment, url_line_start, LINE_WINDOW)
                    if located:
                        located["source"] = "url_file_at_parent"

        detection = detect_satd_fix_commit(
            repo_path=repo_path,
            satd_commit=commit_hash,
            satd_comment=satd_comment,
            file_path=file_path,
            satd_line_number=located["matched_line_number"] if located else url_line_start,
        )

        detection.repo_slug = repo_slug
        detection.url_revision = url_info["revision"]
        detection.url_file_path = url_file_path
        detection.url_line_start = url_line_start

        if located:
            detection.matched_file = file_path
            detection.matched_line_number = located["matched_line_number"]
            detection.matched_line_text = located["matched_line_text"]
            detection.line_match_similarity = located["similarity"]
            detection.line_match_source = located["source"]
        else:
            detection.matched_file = file_path
            if detection.status == DetectionStatus.COMMENT_NOT_FOUND:
                detection.details = (
                    "SATD comment could not be located in the URL file "
                    "at the given commit or its parent."
                )

        return detection.to_dict()

    except Exception as e:
        import traceback
        return DetectionResult(
            status=DetectionStatus.ERROR,
            details=f"{str(e)}\n{traceback.format_exc()}",
        ).to_dict()


# =========================================================
# Main
# =========================================================
def main():
    if not os.path.exists(INPUT_EXCEL):
        raise FileNotFoundError(f"Input file not found: {INPUT_EXCEL}")

    df = pd.read_excel(INPUT_EXCEL, usecols=[COL_COMMENT, COL_URL])

    required = {COL_COMMENT, COL_URL}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    results = []
    total = len(df)

    for i, row in enumerate(df.itertuples(index=False), start=1):
        print(f"[{i}/{total}] Processing...")
        row_dict = {COL_COMMENT: row.comment, COL_URL: row.url}
        results.append(process_row(row_dict, REPOS_DIR, fetch_repos=False))

    out_df = pd.concat([df.reset_index(drop=True), pd.DataFrame(results)], axis=1)

    os.makedirs(os.path.dirname(OUTPUT_EXCEL), exist_ok=True)
    out_df.to_excel(OUTPUT_EXCEL, index=False)

    print(f"\nDone. Results saved to: {OUTPUT_EXCEL}")

    status_counts = out_df["status"].value_counts()
    print("\n=== Summary ===")
    print(status_counts)

    if "fix_type" in out_df.columns:
        fix_type_counts = out_df[out_df["status"] == "fix_found"]["fix_type"].value_counts()
        print("\n=== Fix Types ===")
        print(fix_type_counts)


if __name__ == "__main__":
    main()
