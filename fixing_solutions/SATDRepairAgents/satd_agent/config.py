from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
import os


@dataclass
class SATDAgentConfig:
    """Runtime configuration for the baseline and agentic SATD pipelines."""

    repos_dir: Path = Path(r"C:\satd_microservice\repos\clones")
    use_double_underscore_repo_dir: bool = True

    input_excel: Path = Path(r"C:\fixing_SATD\results\SATD_2years_fixed_Final.xlsx")
    output_excel: Path = Path(r"C:\fixing_SATD\results\SATDRepairAgent_results.xlsx")

    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "https://etsmtl.ca")
    openrouter_app_name: str = os.getenv("OPENROUTER_APP_NAME", "SATD-Agent")

       # Configure SATD_CODEX_CLI_COMMAND as a format string. The command should print
    # JSON to stdout and accept these placeholders:
    #   {system_prompt_file}
    #   {user_prompt_file}
    #
    # Example if your local CLI supports file-based prompts:
    #   SATD_CODEX_CLI_COMMAND='codex exec --json --system-file "{system_prompt_file}" --prompt-file "{user_prompt_file}"'
    #
    # If this is empty or the local command fails, the code falls back to the API.
    use_local_codex_for_exploration: bool = os.getenv("SATD_USE_LOCAL_CODEX_FOR_EXPLORATION", "1") == "1"
    codex_cli_command: str = os.getenv("SATD_CODEX_CLI_COMMAND", "")
    codex_cli_timeout_seconds: int = int(os.getenv("SATD_CODEX_CLI_TIMEOUT_SECONDS", "180"))

    github_token: str = os.getenv("github", "")

    # Recommended main setup for the dissertation:
    # one orchestrating SATD-Agent with two explicit agents:
    # - generator agent: understanding + planning + patch generation
    # - judge agent: validation / judging
    #
    # Change SATD_AGENT_MODEL in the environment if your provider uses a different
    # Codex identifier.
    generator_model: str = os.getenv("SATD_AGENT_GENERATOR_MODEL", "openai/gpt-5.2-codex")
    judge_model: str = os.getenv("SATD_AGENT_JUDGE_MODEL", os.getenv("SATD_AGENT_GENERATOR_MODEL", "openai/gpt-5.2-codex"))

    # Optional comparison models for later experiments.
    comparison_models: List[str] = field(
        default_factory=lambda: [
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-pro",
            "google/gemma-4-27b-it",
        ]
    )

    # By default, the generator stages use the generator model and the validation
    # stage uses the judge model. You can still override a specific stage later
    # for ablations if you want a hybrid pipeline.
    stage_models: Dict[str, str] = field(default_factory=dict)

    # Whether to run only the main Codex pipeline or compare additional models.
    run_comparison_models: bool = False

    temperature: float = 0.1
    sleep_between_calls: float = 0.5

    # Retrieval sizes
    local_context_before: int = 30
    local_context_after: int = 30
    max_related_commits: int = 5
    max_test_files: int = 5
    max_dependency_files: int = 5
    max_search_hits: int = 10
    max_github_discussions: int = 5

    # Optional semantic retrieval knobs
    enable_qdrant: bool = os.getenv("ENABLE_QDRANT", "0") == "1"
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "satd-agent-context")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # LangGraph is preferred, but the code falls back to a sequential pipeline if missing.
    prefer_langgraph: bool = True

    def model_for_stage(self, stage_name: str) -> str:
        default_map = {
            "exploration": self.generator_model,
            "understanding": self.generator_model,
            "planning": self.generator_model,
            "patch_generation": self.generator_model,
            "validation": self.judge_model,
        }
        return self.stage_models.get(stage_name, default_map.get(stage_name, self.generator_model))

    def experiment_models(self) -> List[str]:
        if self.run_comparison_models:
            return [self.generator_model, *self.comparison_models]
        return [self.generator_model]
