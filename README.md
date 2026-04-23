# SATD Repair Project

This repository contains the data, scripts, prompts, and experimental results used to study automated repair of SATD (Self-Admitted Technical Debt) comments.

SATD comments are developer-written comments that explicitly mention technical debt, for example:

- workaround or hack comments
- missing logic
- incomplete implementations
- temporary solutions
- design limitations to be fixed later


## Project Goal

The goal of the project is to evaluate different approaches for repairing SATD comments by comparing generated fixes against developer-authored fixing commits.

The repository includes:

- the SATD dataset
- the ground-truth fixing commits
- baseline repair approaches
- the proposed `SATDRepairAgents` pipeline
- result files for all approaches

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

- `README.md`
  - main repository documentation
- `README_SATD_AGENT.md`
  - complementary project overview
- `satd_Track_finale.py`
  - script used to identify the fixing commit for SATD instances
- `requirements.txt`
  - Python dependencies for the project

## Ground Truth

The ground-truth dataset is located in:

- `results\SATD_2years_fixed_Final.xlsx`

This file contains the SATD instances together with the identified fixing commit and related metadata used for evaluation.

## Repair Approaches

All repair approaches are located under:

- `fixing_solutions`

### 1. Proposed approach: `SATDRepairAgents`

Folder:

- `fixing_solutions\SATDRepairAgents`

This folder contains the proposed SATD repair agent pipeline.

#### Solution overview

`SATDRepairAgents` is an agentic repair pipeline in which the explorer agent is responsible for repository retrieval and repository exploration before the downstream understanding, planning, patch generation, and validation stages.

The implementation is organized around the class:

- `fixing_solutions\SATDRepairAgents\satd_agent\pipeline.py`

and is executed through:

- `fixing_solutions\SATDRepairAgents\run_agent.py`

#### Pipeline stages

For each SATD instance, the pipeline performs the following steps:

1. Context retrieval
   - retrieves local repository context from the cloned repository
   - gathers surrounding code, recent commit history, dependency files, likely tests, and lexical search hits
   - when GitHub access is configured, also retrieves PR-linked context centered on the fixing commit
2. Repository exploration
   - uses a local Codex explorer when configured
   - summarizes repository structure and likely repair-relevant artifacts
3. SATD understanding
   - interprets the debt comment
   - identifies likely service, root cause, and repair scope
4. Fix planning
   - predicts the repair type
   - generates a short implementation plan
5. Patch generation
   - proposes the repair
   - returns touched files and patch format
6. Validation
   - judges syntactic plausibility
   - estimates localization quality
   - returns validation and fix confidence

#### Agent roles

The proposed solution is organized as an explicit multi-stage agent pipeline:

- explorer agent
  - performs repository retrieval and artifact collection
  - gathers surrounding code, commit history, dependency files, related tests, lexical search hits, and PR-related artifacts
  - performs repository exploration and summarization
  - can use local Codex CLI
- generator agent
  - SATD understanding
  - fix planning
  - patch generation
- judge agent
  - validation and confidence estimation

#### Input and output

By default, the runner:

- reads `results\SATD_2years_fixed_Final.xlsx`
- filters the subset with `status = fix_found`
- runs the repair pipeline instance by instance
- writes the results to `results\SATDRepairAgent_results.xlsx`

Important generated fields include:

- `agent_fix_kind`
- `agent_predicted_fix_category`
- `agent_rationale`
- `agent_proposed_fix`
- `agent_patch_format`
- `agent_touched_files`
- `validation_status`
- `validation_syntactic_validity`
- `validation_localization_accuracy`
- `validation_confidence`
- `fix_confidence`
- `step_trace_json`

#### Pull-request retrieval

When a GitHub token is configured, `SATDRepairAgents` enriches local repository retrieval with PR artifacts.

The PR retriever first looks up pull requests linked directly to the `fix_commit`, and then collects:

- PR title
- PR body / description
- PR URL
- PR state
- merge status and merge time
- changed-file count
- commit count
- issue-comment count
- review-comment count
- changed files with truncated patch snippets
- top-level PR comments
- inline review comments

In addition to commit-linked PR retrieval, the agent still performs lightweight GitHub search over repository discussions using the SATD file name and SATD comment text. All retrieved PR and discussion artifacts are injected into the hybrid context alongside local code, recent commits, dependency files, and related tests before downstream understanding, planning, and patch generation.

#### Configuration

The main runtime configuration is defined in:

- `fixing_solutions\SATDRepairAgents\satd_agent\config.py`

Important configurable items include:

- local cloned repositories directory
- input and output Excel paths
- generator model
- judge model
- whether to use local Codex for exploration
- retrieval window sizes
- whether to run only the main agent or additional comparison models

By default, the main generator model is:

- `openai/gpt-5.2-codex`

#### Important files

- `fixing_solutions\SATDRepairAgents\run_agent.py`
  - main script used to run the SATDRepairAgents approach
- `fixing_solutions\SATDRepairAgents\requirements_satd_agent.txt`
  - dependencies for the SATDRepairAgents pipeline
- `fixing_solutions\SATDRepairAgents\satd_agent\config.py`
  - runtime configuration
- `fixing_solutions\SATDRepairAgents\satd_agent\pipeline.py`
  - staged orchestration of the agent workflow
- `fixing_solutions\SATDRepairAgents\satd_agent\retrieval.py`
  - local and hybrid context retrieval
- `fixing_solutions\SATDRepairAgents\satd_agent\explorer.py`
  - repository exploration layer
- `fixing_solutions\SATDRepairAgents\satd_agent\llm.py`
  - model calling logic
- `fixing_solutions\SATDRepairAgents\satd_agent\prompts.py`
  - prompts for understanding, planning, patching, and validation
- `fixing_solutions\SATDRepairAgents\satd_agent\schemas.py`
  - structured input and output schemas

#### Run

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

1. Read `README.md`
2. Inspect `data\SATD_2years.xlsx`
3. Inspect `results\SATD_2years_fixed_Final.xlsx`
4. Review the approach folders under `fixing_solutions`
5. Run `fixing_solutions\SATDRepairAgents\run_agent.py`
6. Compare outputs in the `results` subfolders

## Summary

In short:

- `data` contains the SATD comments
- `results\SATD_2years_fixed_Final.xlsx` contains the ground truth with fixing commits
- `fixing_solutions\SATDRepairAgents` contains the proposed agentic repair solution
- `fixing_solutions\LLMs` contains the LLM baselines
- `fixing_solutions\codexAgent` contains the two Codex prompt variants
- `results\LLM`, `results\Codex`, and `results\SATDRepairAgents` contain the outputs of each approach
- `satd_Track_finale.py` is the script used to identify fixing commits
