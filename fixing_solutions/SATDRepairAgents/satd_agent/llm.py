from __future__ import annotations

import json
import re
import time
from typing import Any, Dict

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at runtime
    OpenAI = None


def clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class SATDAgentLLM:
    """
    Structured LLM wrapper for the generator and judge agents.

    This wrapper intentionally does not call the local Codex CLI. Local Codex is
    reserved for repository exploration so generation and judging remain easy to
    batch, parse, and compare.
    """

    def __init__(self, config):
        self.config = config
        self.client = None
        if OpenAI is not None and config.openrouter_api_key:
            self.client = OpenAI(
                api_key=config.openrouter_api_key,
                base_url=config.openrouter_base_url,
                default_headers={
                    "HTTP-Referer": config.openrouter_site_url,
                    "X-Title": config.openrouter_app_name,
                },
            )

    def call_json(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        fallback: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.client is None:
            raise RuntimeError(
                "OpenRouter client is unavailable. Ensure the 'openai' package is installed "
                "and OPENROUTER_API_KEY is loaded into the environment (for example via the project .env file)."
            )

        response = self.client.chat.completions.create(
            model=model_name,
            temperature=self.config.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = (response.choices[0].message.content or "").strip()
        cleaned = clean_json_text(raw_text)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return dict(fallback)

    def maybe_sleep(self) -> None:
        if self.config.sleep_between_calls > 0:
            time.sleep(self.config.sleep_between_calls)
