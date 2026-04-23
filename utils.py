import os
import json
from typing import Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")


def truncate_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    return text[:max_chars]


def llm_judge_retained_resolution(
    satd_comment: str,
    commit_message: str,
    before_snippet: str,
    after_snippet: str,
    diff_excerpt: str
) -> Dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {
            "label": "uncertain",
            "reason": "OPENROUTER_API_KEY is missing",
            "used_llm": False
        }

    client = OpenAI(
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=api_key
    )

    system_prompt = (
        "You are assessing whether the technical debt described by a self-admitted "
        "technical debt comment appears resolved after a commit, even if the comment remains. "
        "Be conservative. Output strict JSON only."
    )

    user_prompt = f"""
SATD comment:
{satd_comment}

Commit message:
{commit_message}

Code before commit:
{truncate_text(before_snippet, 3500)}

Code after commit:
{truncate_text(after_snippet, 3500)}

Diff excerpt:
{truncate_text(diff_excerpt, 3500)}

Task:
Decide whether the underlying issue described by the SATD comment appears resolved after the commit.

Allowed labels:
- resolved
- partially_resolved
- not_resolved
- uncertain

Rules:
- Use "resolved" only if the code change strongly suggests the issue is addressed.
- Use "partially_resolved" if there is improvement but not full resolution.
- Use "not_resolved" if the problem still appears present.
- Use "uncertain" if evidence is insufficient.

Return JSON exactly like:
{{"label":"resolved","reason":"brief reason"}}
""".strip()

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            extra_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost"),
                "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_NAME", "SATD Resolution Miner"),
            },
        )

        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)

        label = data.get("label", "uncertain")
        if label not in {"resolved", "partially_resolved", "not_resolved", "uncertain"}:
            label = "uncertain"

        return {
            "label": label,
            "reason": data.get("reason", ""),
            "used_llm": True
        }

    except Exception as e:
        return {
            "label": "uncertain",
            "reason": f"LLM error: {e}",
            "used_llm": True
        }