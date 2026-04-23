from __future__ import annotations

from typing import Any, Dict
from typing import List

from .schemas import RetrievedArtifact, SATDInstance


class GitHubDiscussionRetriever:
    """
    Optional GitHub issue/PR discussion retriever.

    This is intentionally lightweight:
    - it uses repository-scoped REST search
    - it is disabled if no GitHub token is configured
    - it returns empty results when anything fails
    """

    def __init__(self, config):
        self.config = config
        self.enabled = bool(config.github_token)
        self._headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }

    def retrieve(self, instance: SATDInstance) -> List[RetrievedArtifact]:
        if not self.enabled:
            return []

        try:
            import requests
        except Exception:
            return []

        artifacts: List[RetrievedArtifact] = []
        artifacts.extend(self._linked_pr_artifacts(requests, instance))
        artifacts.extend(self._search_discussion_artifacts(requests, instance))
        return artifacts

    def _linked_pr_artifacts(self, requests, instance: SATDInstance) -> List[RetrievedArtifact]:
        if not instance.fix_commit:
            return []

        pulls_url = f"https://api.github.com/repos/{instance.repo_slug}/commits/{instance.fix_commit}/pulls"
        pulls = self._get_json(
            requests,
            pulls_url,
            params={"per_page": self.config.max_github_discussions},
        )
        if not isinstance(pulls, list):
            return []

        artifacts: List[RetrievedArtifact] = []
        for pr in pulls[: self.config.max_github_discussions]:
            if not isinstance(pr, dict):
                continue
            artifacts.extend(self._pr_artifacts(requests, instance, pr))
        return artifacts

    def _pr_artifacts(self, requests, instance: SATDInstance, pr_stub: Dict[str, Any]) -> List[RetrievedArtifact]:
        number = pr_stub.get("number")
        if not number:
            return []

        pr_url = f"https://api.github.com/repos/{instance.repo_slug}/pulls/{number}"
        pr = self._get_json(requests, pr_url)
        if not isinstance(pr, dict):
            pr = pr_stub

        pr_title = pr.get("title", "") or pr_stub.get("title", "")
        pr_html_url = pr.get("html_url", "") or pr_stub.get("html_url", "")
        pr_body = (pr.get("body") or pr_stub.get("body") or "")[:5000]
        pr_state = pr.get("state", "") or pr_stub.get("state", "")

        metadata = {
            "number": number,
            "state": pr_state,
            "merged": pr.get("merged", ""),
            "merged_at": pr.get("merged_at", ""),
            "changed_files": pr.get("changed_files", ""),
            "additions": pr.get("additions", ""),
            "deletions": pr.get("deletions", ""),
            "commits": pr.get("commits", ""),
            "comments": pr.get("comments", ""),
            "review_comments": pr.get("review_comments", ""),
        }

        artifacts: List[RetrievedArtifact] = [
            RetrievedArtifact(
                artifact_type="github_pr",
                title=pr_title,
                location=pr_html_url,
                content=self._format_pr_summary(pr, pr_body),
                score=0.8,
                metadata=metadata,
            )
        ]

        files_url = f"https://api.github.com/repos/{instance.repo_slug}/pulls/{number}/files"
        files = self._get_json(
            requests,
            files_url,
            params={"per_page": min(self.config.max_pr_files, 100)},
        )
        if isinstance(files, list) and files:
            artifacts.append(
                RetrievedArtifact(
                    artifact_type="github_pr_files",
                    title=f"Changed files for PR #{number}",
                    location=pr_html_url,
                    content=self._format_pr_files(files[: self.config.max_pr_files]),
                    score=0.7,
                    metadata={"number": number, "file_count": len(files)},
                )
            )

        issue_comments_url = f"https://api.github.com/repos/{instance.repo_slug}/issues/{number}/comments"
        issue_comments = self._get_json(
            requests,
            issue_comments_url,
            params={"per_page": min(self.config.max_pr_issue_comments, 100)},
        )
        if isinstance(issue_comments, list) and issue_comments:
            artifacts.append(
                RetrievedArtifact(
                    artifact_type="github_pr_issue_comments",
                    title=f"Issue comments for PR #{number}",
                    location=pr_html_url,
                    content=self._format_pr_comments(issue_comments[: self.config.max_pr_issue_comments]),
                    score=0.6,
                    metadata={"number": number, "comment_count": len(issue_comments)},
                )
            )

        review_comments_url = f"https://api.github.com/repos/{instance.repo_slug}/pulls/{number}/comments"
        review_comments = self._get_json(
            requests,
            review_comments_url,
            params={"per_page": min(self.config.max_pr_review_comments, 100)},
        )
        if isinstance(review_comments, list) and review_comments:
            artifacts.append(
                RetrievedArtifact(
                    artifact_type="github_pr_review_comments",
                    title=f"Review comments for PR #{number}",
                    location=pr_html_url,
                    content=self._format_pr_review_comments(review_comments[: self.config.max_pr_review_comments]),
                    score=0.6,
                    metadata={"number": number, "review_comment_count": len(review_comments)},
                )
            )

        return artifacts

    def _search_discussion_artifacts(self, requests, instance: SATDInstance) -> List[RetrievedArtifact]:
        file_name = instance.url_file_path.split("/")[-1] if instance.url_file_path else ""
        query = f'repo:{instance.repo_slug} "{file_name}" "{instance.comment[:40]}"'
        url = "https://api.github.com/search/issues"
        data = self._get_json(
            requests,
            url,
            params={"q": query, "per_page": self.config.max_github_discussions},
        )
        if not isinstance(data, dict):
            return []

        artifacts: List[RetrievedArtifact] = []
        for item in data.get("items", [])[: self.config.max_github_discussions]:
            if not isinstance(item, dict):
                continue
            artifact_type = "github_pr_search_hit" if "/pull/" in (item.get("html_url") or "") else "github_discussion"
            artifacts.append(
                RetrievedArtifact(
                    artifact_type=artifact_type,
                    title=item.get("title", ""),
                    location=item.get("html_url", ""),
                    content=(item.get("body") or "")[:3000],
                    score=0.4,
                    metadata={"state": item.get("state", ""), "number": item.get("number", "")},
                )
            )
        return artifacts

    def _get_json(self, requests, url: str, params: Dict[str, Any] | None = None) -> Any:
        try:
            resp = requests.get(
                url,
                headers=self._headers,
                params=params or {},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _format_pr_summary(self, pr: Dict[str, Any], body: str) -> str:
        lines = [
            f"PR #{pr.get('number', '')}: {pr.get('title', '')}",
            f"State: {pr.get('state', '')}, merged: {pr.get('merged', '')}, merged_at: {pr.get('merged_at', '')}",
            f"Changed files: {pr.get('changed_files', '')}, commits: {pr.get('commits', '')}, comments: {pr.get('comments', '')}, review_comments: {pr.get('review_comments', '')}",
        ]
        if body:
            lines.extend(["", "Body:", body])
        return "\n".join(lines).strip()

    def _format_pr_files(self, files: List[Dict[str, Any]]) -> str:
        lines = []
        for item in files:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"{item.get('filename', '')} | status={item.get('status', '')} | additions={item.get('additions', '')} | deletions={item.get('deletions', '')}"
            )
            patch = (item.get("patch") or "")[:1200]
            if patch:
                lines.append(patch)
        return "\n\n".join(lines).strip()

    def _format_pr_comments(self, comments: List[Dict[str, Any]]) -> str:
        lines = []
        for item in comments:
            if not isinstance(item, dict):
                continue
            author = ((item.get("user") or {}).get("login", "")) if isinstance(item.get("user"), dict) else ""
            body = (item.get("body") or "")[:1200]
            lines.append(f"{author}: {body}".strip())
        return "\n\n".join(lines).strip()

    def _format_pr_review_comments(self, comments: List[Dict[str, Any]]) -> str:
        lines = []
        for item in comments:
            if not isinstance(item, dict):
                continue
            author = ((item.get("user") or {}).get("login", "")) if isinstance(item.get("user"), dict) else ""
            path = item.get("path", "")
            line_no = item.get("line", "")
            body = (item.get("body") or "")[:1200]
            lines.append(f"{author} on {path}:{line_no} -> {body}".strip())
        return "\n\n".join(lines).strip()
