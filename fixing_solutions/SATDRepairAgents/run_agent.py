from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

import pandas as pd

from satd_agent.config import SATDAgentConfig
from satd_agent.pipeline import SATDAgentPipeline, build_langgraph_pipeline_if_available
from satd_agent.schemas import SATDInstance


REQUIRED_COLUMNS = [
    "url",
    "comment",
    "status",
    "repo_slug",
    "url_revision",
    "url_file_path",
    "url_line_start",
    "fix_commit",
    "fix_type",
    "fix_message",
]


def validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in input Excel: {missing}")


def row_to_instance(row: pd.Series) -> SATDInstance:
    return SATDInstance(
        url=str(row.get("url", "")).strip(),
        comment=str(row.get("comment", "")).strip(),
        status=str(row.get("status", "")).strip(),
        repo_slug=str(row.get("repo_slug", "")).strip(),
        url_revision=str(row.get("url_revision", "")).strip(),
        url_file_path=str(row.get("url_file_path", "")).strip(),
        url_line_start=int(row.get("url_line_start", 0)),
        fix_commit=str(row.get("fix_commit", "")).strip(),
        fix_type=str(row.get("fix_type", "")).strip(),
        fix_message=str(row.get("fix_message", "")).strip(),
    )


def run_one_model(df: pd.DataFrame, config: SATDAgentConfig, model_name: str) -> List[Dict]:
    pipeline = SATDAgentPipeline(config)
    results: List[Dict] = []

    # This compiled graph is optional. We keep the sequential runner as the default
    # because it is simpler to debug, but this helper shows how the same stages can
    # be orchestrated in a graph-based workflow.
    _compiled_graph = build_langgraph_pipeline_if_available(config) if config.prefer_langgraph else None

    total = len(df)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        instance = row_to_instance(row)
        print(f"[{model_name}] [{i}/{total}] {instance.repo_slug} :: {instance.url_file_path} @ {instance.url_revision}")
        result = pipeline.run(instance, model_name)
        results.append(result.to_flat_dict())
        if config.sleep_between_calls > 0:
            time.sleep(config.sleep_between_calls)
    return results


def main() -> None:
    config = SATDAgentConfig()
    df = pd.read_excel(config.input_excel)
    validate_columns(df)

    # Match the dissertation setup: evaluate only the resolved subset against ground truth.
    df = df[df["status"].astype(str).str.strip().str.lower() == "fix_found"].copy()
    print(f"Total fix_found SATD instances: {len(df)}")
    print(f"Generator agent model: {config.generator_model}")
    print(f"Judge agent model: {config.judge_model}")

    all_results: List[Dict] = []
    for model_name in config.experiment_models():
        all_results.extend(run_one_model(df, config, model_name))

    out_df = pd.DataFrame(all_results)
    config.output_excel.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_excel(config.output_excel, index=False)

    print(f"\nDone. Results saved to: {config.output_excel}")
    print("Framework choice: LangGraph-style staged pipeline with sequential fallback.")


if __name__ == "__main__":
    main()
