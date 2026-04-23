# SATD Repair Project

This repository contains the data, scripts, prompts, and experimental results used to study automated repair of SATD (Self-Admitted Technical Debt) comments.

SATD comments are developer-written comments that explicitly mention technical debt, for example:

- workaround or hack comments
- missing logic
- incomplete implementations
- temporary solutions
- design limitations to be fixed later

The project root is:

- `C:\fixing_SATD`

## Project Structure

### Top-level folders

- `data`
  - contains the SATD comment dataset
  - current dataset file: `SATD_2years.xlsx`
- `fixing_solutions`
  - contains the repair approaches, prompts, and runnable scripts
- `results`
  - contains the ground truth and the generated outputs of each approach
- `repos_cache`
  - local cache used by the project

### Main top-level files

- `README_SATD_AGENT.md`
  - project overview
- `satd_Track_finale.py`
  - script used to identify the fixing commit for SATD instances
- `requirements.txt`
  - Python dependencies for the project

## Ground Truth

The ground-truth file is located in:

- `results\SATD_2years_fixed_Final.xlsx`

This file contains the SATD instances together with the identified fixing commit and related metadata used for evaluation.

## Repair Approaches

All repair approaches are located under:

- `fixing_solutions`

### 1. Proposed approach: `SATDRepairAgents`

Folder:

- `fixing_solutions\SATDRepairAgents`

This folder contains the proposed SATD repair agent pipeline.

Important files:

- `fixing_solutions\SATDRepairAgents\run_agent.py`
  - main script used to run the SATDRepairAgents approach
- `fixing_solutions\SATDRepairAgents\requirements_satd_agent.txt`
  - dependencies for the SATDRepairAgents pipeline
- `fixing_solutions\SATDRepairAgents\satd_agent`
  - internal implementation of the agent pipeline

To run the SATDRepairAgents approach:

```bash
python fixing_solutions\SATDRepairAgents\run_agent.py
```

### 2. LLM baselines

Folder:

- `fixing_solutions\LLMs`

The LLM baselines used in this project are:

- `anthropic/claude-sonnet-4-5`
- `openai/gpt-5-mini-2025-08-07`

Important files:

- `fixing_solutions\LLMs\LLMs_fix.py`
  - script for running the LLM baselines
- `fixing_solutions\LLMs\baseline_prompt.txt`
  - prompt used for the LLM baseline runs

### 3. Codex agent baselines

Folder:

- `fixing_solutions\codexAgent`

Two Codex-based variants are used:

- Codex with local repository context
- Codex with local repository context plus pull-request context

Important files:

- `fixing_solutions\codexAgent\codex_prompt.txt`
  - prompt for the local-context Codex version
- `fixing_solutions\codexAgent\codex_prompt_PR.txt`
  - prompt for the PR-context Codex version

## Results

The generated outputs are stored in `results`, with one subfolder per approach.

### Ground truth and evaluation artifacts

- `results\SATD_2years_fixed_Final.xlsx`
  - ground truth with fixing commits
- `results\SATD_Repair_Comparison.xlsx`
  - comparison workbook across approaches

### LLM baseline results

Folder:

- `results\LLM`

Files:

- `results\LLM\Fix_LLM_results.xlsx`
  - results for `openai/gpt-5-mini-2025-08-07`
- `results\LLM\Fix_Claude_results.xlsx`
  - results for `anthropic/claude-sonnet-4-5`

### Codex baseline results

Folder:

- `results\Codex`

Files:

- `results\Codex\Codex_Fix_results.xlsx`
  - Codex with local context
- `results\Codex\Codex_Fix_PR_results.xlsx`
  - Codex with local context plus PR context

### SATDRepairAgents results

Folder:

- `results\SATDRepairAgents`

Files:

- `results\SATDRepairAgents\SATDRepairAgent_results.xlsx`
  - output of the proposed SATDRepairAgents approach

## Recommended Reading Order

If you are new to the project, the easiest order is:

1. Read `README_SATD_AGENT.md`
2. Inspect `data\SATD_2years.xlsx`
3. Inspect `results\SATD_2years_fixed_Final.xlsx`
4. Review the approach folders under `fixing_solutions`
5. Run `fixing_solutions\SATDRepairAgents\run_agent.py`
6. Compare outputs in the `results` subfolders

## Summary

In short:

- `data` contains the SATD comments
- `results\SATD_2years_fixed_Final.xlsx` contains the ground truth with fixing commits
- `fixing_solutions\SATDRepairAgents` contains the proposed approach
- `fixing_solutions\LLMs` contains the LLM baselines
- `fixing_solutions\codexAgent` contains the two Codex prompt variants
- `results\LLM`, `results\Codex`, and `results\SATDRepairAgents` contain the outputs of each approach
- `satd_Track_finale.py` is the script used to identify fixing commits
