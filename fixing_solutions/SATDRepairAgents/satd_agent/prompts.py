EXPLORATION_SYSTEM_PROMPT = """You are a repository exploration assistant specialized in SATD repair.
Return only valid JSON.
"""

EXPLORATION_USER_PROMPT = """Analyze the retrieved repository artifacts for this SATD instance.

SATD definition:
SATD (Self-Admitted Technical Debt) is a developer-written comment that explicitly
indicates technical debt, such as a workaround, hack, missing logic, incomplete
implementation, design limitation, or temporary solution that should later be
repaired or improved.

Repository:
{repo_slug}

Local repository path:
{repo_dir}

SATD comment:
{comment}

Observed file:
{file_path}

Observed line:
{line_number}

Retrieved context:
{retrieved_context}

Return JSON with:
- service_context
- relevant_files         # list of key files to inspect or change
- dependency_notes
- test_notes             # why likely related test files matter for this SATD
- commit_notes           # what recent commits suggest about the affected code
- exploration_notes
- summary                # compact repository exploration summary for downstream agents

Important:
- Do not return dataset metadata such as url, fix_commit, fix_type, or fix_message.
- Focus only on repository-level evidence that may help repair the SATD.
- Treat the local repository path as the primary workspace root if you need to inspect
  code or infer where related files live.
"""


UNDERSTANDING_SYSTEM_PROMPT = """You are an expert software maintenance and SATD analysis assistant.
Return only valid JSON.
"""

UNDERSTANDING_USER_PROMPT = """Analyze this SATD instance for a microservice repository.

SATD definition:
SATD (Self-Admitted Technical Debt) is a developer-written comment that explicitly
indicates technical debt, such as a workaround, hack, missing logic, incomplete
implementation, design limitation, or temporary solution that should later be
repaired or improved.

SATD comment:
{comment}

Observed file:
{file_path}

Observed line:
{line_number}

Local context:
{local_context}

Repository exploration summary:
{exploration_summary}

Return JSON with:
- debt_summary
- likely_service
- likely_root_cause
- likely_fix_scope
- notes

Important:
- Do not return dataset metadata such as url, fix_commit, fix_type, or fix_message.
- Interpret the SATD comment using both the local code and the exploration summary.
"""


PLANNING_SYSTEM_PROMPT = """You are an expert software remediation planner.
Return only valid JSON.
"""

PLANNING_USER_PROMPT = """Design a fix plan for this SATD in a microservice codebase.

Use only the controlled values below.

Understanding:
{understanding_json}

Retrieved context:
{retrieved_context}

Return JSON with:
- fix_kind               # patch | refactoring_suggestion | improvement
- predicted_fix_category # remove_workaround | refactor | implement_missing_logic | configuration_fix | test_fix | unknown
- rationale
- implementation_plan    # list of short repair steps
- confidence             # float between 0.0 and 1.0

Important:
- Do not generate the actual fix in this stage.
- Do not return dataset metadata such as url, fix_commit, fix_type, or fix_message.
- Use only the allowed values for fix_kind and predicted_fix_category.
"""


PATCH_SYSTEM_PROMPT = """You are an expert software maintenance assistant that proposes concrete SATD fixes.
Return only valid JSON.
"""

PATCH_USER_PROMPT = """Generate a proposed fix for this SATD instance.

SATD comment:
{comment}

Understanding:
{understanding_json}

Fix plan:
{plan_json}

Retrieved context:
{retrieved_context}

Return JSON with:
- proposed_fix
- patch_format          # unified_diff | pseudo_patch | code_snippet | text
- touched_files         # list of file paths

Important:
- Use the fix plan as a constraint.
- Do not return dataset metadata such as url, fix_commit, fix_type, or fix_message.
- Do not repeat planning fields unless needed inside the proposed_fix text itself.
"""


VALIDATION_SYSTEM_PROMPT = """You are an expert code reviewer validating an LLM-generated SATD fix.
Return only valid JSON.
"""

VALIDATION_USER_PROMPT = """Validate the proposed fix for this SATD instance.

SATD definition:
SATD (Self-Admitted Technical Debt) is a developer-written comment that explicitly
indicates technical debt, such as a workaround, hack, missing logic, incomplete
implementation, design limitation, or temporary solution that should later be
repaired or improved.

SATD comment:
{comment}

Retrieved context:
{retrieved_context}

Proposed fix:
{proposed_fix}

Return JSON with:
- validation_status        # valid | partially_valid | invalid | uncertain
- syntactic_validity       # likely_valid | unknown | likely_invalid
- localization_accuracy    # high | medium | low
- validation_confidence    # float between 0.0 and 1.0
- fix_confidence           # float between 0.0 and 1.0
- validation_notes

Important:
- Judge only from the SATD comment, the retrieved context, and the proposed fix.
- Do not return dataset metadata such as url, fix_commit, fix_type, or fix_message.
- Confidence values must be numeric and between 0.0 and 1.0.
"""
