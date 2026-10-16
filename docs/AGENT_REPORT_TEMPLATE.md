# Agent Task Report

## 1. Metadata

- **Task ID:** [Unique task identifier]
- **Task title:** [Short descriptive title]
- **Date:** [YYYY-MM-DD HH:mm timezone]
- **Repository:** [Repository name]
- **Branch:** [Branch name]
- **Commit SHA:** [Exact commit SHA, if available]
- **Task status:** `PASS` / `PASS_WITH_ISSUES` / `FAIL` / `BLOCKED`
- **Related reports:** [Links to relevant previous reports, or None]

## 2. Executive Summary

### Decision

[State the outcome and what it means.]

### Completed
- [Key completed item]
- [Key completed item]

### Important Findings
- [Most important finding, defect, or limitation]
- [Remaining blocker, or None]

### Next Recommended Action

[One specific next step. Do not automatically begin it unless authorized.]

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Notes |
|---|---|---|---|---|
| R1 | [Requirement] | PASS/PARTIAL/FAIL/N/A | [File, test, calculation, or output] | [Details] |
| R2 | [Requirement] | PASS/PARTIAL/FAIL/N/A | [Evidence] | [Details] |

State explicitly which requested requirements were not completed and why.

## 4. Implementation Summary

Describe what changed and how it works.

| Component/File | Change | Reason |
|---|---|---|
| [Path] | [Change made] | [Reason] |

Distinguish between:
- Implemented and verified.
- Implemented but not fully verified.
- Investigated but not changed.
- Not implemented.

## 5. Results and Evidence

Present the actual results relevant to the task.

For quantitative results, include:
- Metric definition and formula where relevant.
- Sample size and filtering criteria.
- Data or configuration used.
- Before-and-after comparison when applicable.
- Units, date range, and important assumptions.

For code or system changes, include:
- Relevant paths, functions, or modules.
- Representative input and output.
- Reproduction steps where useful.
- Evidence supporting each important conclusion.

Do not include irrelevant metrics merely to make the report look complete. Mark unavailable or unverified results explicitly.

## 6. Findings, Risks, and Limitations

| ID | Finding | Severity | Evidence | Impact | Status |
|---|---|---|---|---|---|
| F1 | [Finding] | Critical/High/Medium/Low/Info | [Evidence] | [Impact] | Open/Resolved/Accepted |

Separate confirmed defects from hypotheses, assumptions, and unresolved questions.

## 7. Verification

| Check | Command or Method | Result | Evidence/Notes |
|---|---|---|---|
| Unit tests | [Command] | [Actual result] | [Details] |
| Integration tests | [Command or N/A] | [Actual result] | [Details] |
| Linter/type checks | [Command or N/A] | [Actual result] | [Details] |
| Data/integrity checks | [Method or N/A] | [Actual result] | [Details] |
| Manual verification | [Method] | [Actual result] | [Details] |
| Reproducibility/idempotency | [Method or N/A] | [Actual result] | [Details] |

Report actual commands and outcomes. Distinguish tests executed from tests skipped, unavailable, or merely inferred from earlier logs.

Passing tests alone does not prove that a system is correct. Include additional evidence proportionate to the task's risk.

## 8. Files, Artifacts, and Data Changes

- **Files created:** [Paths or None]
- **Files modified:** [Paths or None]
- **Files deleted:** [Paths or None]
- **Data/schema migrations:** [Details or None]
- **Generated artifacts:** [Paths or None]
- **Production state changed:** [Yes/No, with explanation]

Explicitly disclose any changes outside the requested scope.

## 9. Safeguards and Backward Compatibility

- Existing behavior preserved: [Details]
- Interfaces/configurations affected: [Details]
- Production/model/deployment state affected: [Details]
- Backward compatibility: [Verified/Not verified/N/A]
- Rollback or recovery considerations: [Details/N/A]

Confirm compliance with the task's explicit constraints.

## 10. Reproducibility

- **Environment/configuration:** [Relevant details]
- **Data snapshot or input version:** [Identifier or N/A]
- **Commands to reproduce:** [Exact commands]
- **Expected output:** [Expected outcome]
- **Artifact locations:** [Paths or links]

Do not expose secrets, credentials, tokens, or sensitive environment variables.

## 11. Final Decision

- **Acceptance criteria satisfied:** [Yes/No/Partially]
- **Remaining blockers:** [List or None]
- **Known limitations:** [List or None]
- **Next action:** [One specific action]
- **Approval required before proceeding:** [Yes/No, with explanation]

Stop at the end of the requested task. Do not automatically start subsequent work unless explicitly authorized.

## Reporting Rules

1. Base every conclusion on the current code, data, and evidence relevant to this task.
2. Never invent test results, metrics, file paths, commit identifiers, or artifacts.
3. Clearly distinguish observed facts, interpretations, and assumptions.
4. Reference exact repository paths and function names; include line references or commit permalinks when practical.
5. Keep this report concise. Put lengthy logs, detailed tables, and machine-readable results in separate artifacts and link to them.
6. Use `N/A` when a section genuinely does not apply; explain why when useful.
7. If the task is blocked, report the blocker and stop instead of claiming completion.
8. Preserve previous detailed reports. Do not overwrite them unless explicitly requested.
9. Use valid relative Markdown links for files in the repository.
10. Ensure the executive summary, detailed findings, and verification results do not contradict one another.
