from __future__ import annotations

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

    def retrieve(self, instance: SATDInstance) -> List[RetrievedArtifact]:
        if not self.enabled:
            return []

        try:
            import requests
        except Exception:
            return []

        file_name = instance.url_file_path.split("/")[-1] if instance.url_file_path else ""
        query = f'repo:{instance.repo_slug} "{file_name}" "{instance.comment[:40]}"'
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }
        url = "https://api.github.com/search/issues"

        try:
            resp = requests.get(url, headers=headers, params={"q": query, "per_page": self.config.max_github_discussions}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        artifacts: List[RetrievedArtifact] = []
        for item in data.get("items", [])[: self.config.max_github_discussions]:
            artifacts.append(
                RetrievedArtifact(
                    artifact_type="github_discussion",
                    title=item.get("title", ""),
                    location=item.get("html_url", ""),
                    content=(item.get("body") or "")[:3000],
                    score=0.4,
                    metadata={"state": item.get("state", ""), "number": item.get("number", "")},
                )
            )
        return artifacts

