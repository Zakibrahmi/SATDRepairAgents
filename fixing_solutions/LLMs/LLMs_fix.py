import os
import re
import json
import time
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ============================================================
# Configuration
# ============================================================

REPOS_DIR = Path(r"C:/satd_microservice/repos/clones")
# If local repos are stored as owner__repo
USE_DOUBLE_UNDERSCORE_REPO_DIR = True

MODEL_NAME = "anthropic/claude-sonnet-4-5"
CONTEXT_BEFORE = 20
CONTEXT_AFTER = 20
SLEEP_BETWEEN_CALLS = 0.5
TEMPERATURE = 0.2
MODELS = {
    #"gemma":    "google/gemma-4-26b-a4b-it",
    #"gpt":      "openai/gpt-5-mini-2025-08-07",
    #"claude":   "anthropic/claude-sonnet-4-5",
    #"gemini":   "google/gemini-3-flash-preview",
    #"deepseek-r": "deepseek/deepseek-r1",
    #"llama":    "meta-llama/llama-3.3-70b-instruct",
    #"qwen":  "qwen/qwen3-coder-next",
    #"phi-4":    "microsoft/phi-4"
}
client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": "https://etsmtl.ca",
        "X-Title": "SATD Baseline Fix Generation"
    }
)

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

# ============================================================
# Helpers
# ============================================================

def validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in input Excel: {missing}")


def load_prompt_template(prompt_file: str) -> str:
    path = Path(prompt_file)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return path.read_text(encoding="utf-8")


def repo_slug_to_local_dir(repo_slug: str) -> Path:
    repo_slug = repo_slug.strip()
    if USE_DOUBLE_UNDERSCORE_REPO_DIR:
        return REPOS_DIR / repo_slug.replace("/", "__")
    return REPOS_DIR / repo_slug




def run_git_command(args, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check
    )


def git_show_file_at_commit(repo_path: Path, commit_sha: str, file_path: str) -> Optional[str]:
    print(f"Retrieving file content from git: {repo_path} @ {commit_sha} :: {file_path}")
    try:
        result = run_git_command(
            ["git", "-C", str(repo_path), "show", f"{commit_sha}:{file_path}"],
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def extract_local_context_from_text(
    file_text: Optional[str],
    line_number: int,
    before: int = 20,
    after: int = 20
) -> Tuple[str, int, int]:
    if file_text is None:
        return "[FILE NOT FOUND AT SPECIFIED COMMIT]", -1, -1

    lines = file_text.splitlines()
    if not lines:
        return "[EMPTY FILE]", -1, -1

    idx = max(0, int(line_number) - 1)
    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)

    out = []
    for i in range(start, end):
        marker = ">>" if (i + 1) == int(line_number) else "  "
        out.append(f"{marker} {i+1:5d}: {lines[i]}")

    return "\n".join(out), start + 1, end


def build_baseline_prompt(
    prompt_template: str,
    satd_comment: str,
    line_number: int,
    local_context: str
   ) -> str:
    try:
        return prompt_template.format(
            line_number=line_number,
            satd_comment=satd_comment,
            local_context=local_context
        )
    except KeyError as e:
        raise ValueError(
            f"Missing placeholder in prompt template: {e}. "
            "Allowed placeholders are: {line_number}, {satd_comment}, {local_context}"
        )


def clean_json_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def call_openrouter(prompt: str, model_name: str) -> Dict[str, Any]:
    response = client.chat.completions.create(
        model=model_name,
        temperature=TEMPERATURE,
        messages=[
            {
                "role": "system",
                "content": "You are an expert software maintenance assistant. Return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw_text = (response.choices[0].message.content or "").strip()
    cleaned = clean_json_text(raw_text)

    try:
        parsed = json.loads(cleaned)
        return {
            "raw_model_output": raw_text,
            "fix_kind": parsed.get("fix_kind", ""),
            "predicted_fix_type": parsed.get("predicted_fix_type", ""),
            "rationale": parsed.get("rationale", ""),
            "proposed_fix": parsed.get("proposed_fix", ""),
            "confidence": parsed.get("confidence", ""),
            "json_valid": True
        }
    except Exception:
        return {
            "raw_model_output": raw_text,
            "fix_kind": "improvement",
            "predicted_fix_type": "unknown",
            "rationale": "Model output was not valid JSON.",
            "proposed_fix": raw_text,
            "confidence": "low",
            "json_valid": False
        }


def process_row(row: pd.Series, prompt_template: str) -> Dict[str, Any]:
    repo_slug = str(row["repo_slug"]).strip()
    revision = str(row["url_revision"]).strip()
    file_path = str(row["url_file_path"]).strip()
    satd_comment = str(row["comment"]).strip()
    line_number = int(row["url_line_start"])

    repo_path = repo_slug_to_local_dir(repo_slug)

    file_text = git_show_file_at_commit(repo_path, revision, file_path)

    local_context, ctx_start, ctx_end = extract_local_context_from_text(
        file_text=file_text,
        line_number=line_number,
        before=CONTEXT_BEFORE,
        after=CONTEXT_AFTER
    )

    prompt = build_baseline_prompt(
        prompt_template=prompt_template,
        satd_comment=satd_comment,
        line_number=line_number,
        local_context=local_context
    )

    llm_result = call_openrouter(prompt, MODEL_NAME)

    return {
        "url": row.get("url", ""),
        "comment": row.get("comment", ""),

        "baseline_context_start_line": ctx_start,
        "baseline_context_end_line": ctx_end,
        "baseline_local_context": local_context,
        "baseline_context_before": CONTEXT_BEFORE,
        "baseline_context_after": CONTEXT_AFTER,

        "baseline_model": MODEL_NAME,
        "baseline_temperature": TEMPERATURE,
        "baseline_prompt_file": PROMPT_FILE,

        "baseline_fix_kind": llm_result.get("fix_kind", ""),
        "baseline_predicted_fix_type": llm_result.get("predicted_fix_type", ""),
        "baseline_rationale": llm_result.get("rationale", ""),
        "baseline_proposed_fix": llm_result.get("proposed_fix", ""),
        "baseline_confidence": llm_result.get("confidence", ""),
        "baseline_raw_model_output": llm_result.get("raw_model_output", ""),
        "touched_files": llm_result.get("touched_files", []),
        "baseline_json_valid": llm_result.get("json_valid", False),

        "approach_name": "baseline_local_context",
        "processing_status": "ok",
        "error_message": ""
    }

def build_error_row(row: pd.Series, error_message: str) -> Dict[str, Any]:
    return {
        # Keep identifiers and original SATD info for later merge/evaluation
        "url": row.get("url", ""),
        "comment": row.get("comment", ""),
        "status": row.get("status", ""),
        

        "baseline_context_start_line": -1,
        "baseline_context_end_line": -1,
        "baseline_local_context": "",
        "baseline_context_before": CONTEXT_BEFORE,
        "baseline_context_after": CONTEXT_AFTER,

        "baseline_model": MODEL_NAME,
        "baseline_temperature": TEMPERATURE,
        
        "baseline_fix_kind": "",
        "baseline_predicted_fix_type": "",
        "baseline_rationale": "",
        "baseline_proposed_fix": "",
        "baseline_confidence": "",
        "baseline_raw_model_output": "",
        "baseline_json_valid": False,

        "approach_name": "baseline_local_context",
        "processing_status": "error",
        "error_message": error_message
    }


def main(INPUT_EXCEL="", OUTPUT_EXCEL="", PROMPT_FILE=""):
    prompt_template = load_prompt_template(PROMPT_FILE)

    df = pd.read_excel(INPUT_EXCEL)
    validate_columns(df)
    
    df = df[df["status"].astype(str).str.strip().str.lower() == "fix_found"].copy()
    print(f"Total fix_found SATD instances: {len(df)}")

    results = []
    total = len(df)

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        print(f"[{i}/{total}] {row['repo_slug']} :: {row['url_file_path']} @ {row['url_revision']}")
        try:
            result = process_row(row, prompt_template)
        except Exception as e:
            result = build_error_row(row, str(e))

        results.append(result)
        time.sleep(SLEEP_BETWEEN_CALLS)

    out_df = pd.DataFrame(results)
    out_df.to_excel(OUTPUT_EXCEL, index=False)

    print(f"\nDone. Results saved to: {OUTPUT_EXCEL}")
    print(f"Prompt template used: {PROMPT_FILE}")


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).parent.parent  # Go up to workspace root
    INPUT_EXCEL = str(SCRIPT_DIR / "results" / "SATD_2years_fixed_Final.xlsx")
    OUTPUT_EXCEL = str(SCRIPT_DIR / "results" / "LLM" /"Fix_Claude_results.xlsx")
    PROMPT_FILE = str(Path(__file__).parent / "prompts" / "baseline_prompt.txt")
    main(INPUT_EXCEL=INPUT_EXCEL, OUTPUT_EXCEL=OUTPUT_EXCEL, PROMPT_FILE=PROMPT_FILE)