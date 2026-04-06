---
name: review-pr
description: Review pull requests, branch diffs, or commit ranges and return structured code review feedback. Use when asked to review a PR, inspect a diff before merge, compare branches, or provide feedback grouped into architectural concerns, blocking issues, nits, and risks.
---

# Review PR

## Overview

Review the proposed change with a code review mindset. Build enough context to judge correctness, design quality, operational impact, and test coverage, then return findings grouped into four categories: architectural concerns, blocking issues, nits, and risks.

## Workflow

1. Establish scope.
- Identify the base and head revision, PR description, linked issue, and any stated rollout notes.
- Read changed tests, migrations, config, and interface boundaries first because they define the intended behavior and blast radius.

2. Read the diff before drilling into files.
- Determine which subsystems changed, what invariants the code depends on, and where data or control flow crosses boundaries.
- Note high-signal areas: persistence, auth, permissions, background jobs, caching, external APIs, concurrency, and deployment-sensitive changes.

3. Inspect the code and tests together.
- Verify that the implementation matches the intended behavior.
- Check whether tests cover the risky paths instead of only the happy path.
- Look for silent failure modes, partial updates, missing validation, and changes that are hard to reason about or extend.

4. Emit only high-signal feedback.
- Cite concrete evidence with file and line references when possible.
- Prefer a small number of defensible findings over a long list of weak suggestions.
- If the diff is too large to review exhaustively, state the blind spots explicitly.

## Category Rules

### Architectural Concerns

Use for design problems that materially increase maintenance cost or make future change unsafe.

- Flag unclear ownership, duplicated business logic, hidden coupling, invalid layering, leaky abstractions, or poor extension points.
- Explain why the design is brittle and what kind of restructuring would reduce the problem.
- Do not use this bucket for stylistic cleanup or one-off correctness bugs.

### Blocking Issues

Use for defects or omissions that should prevent merge until fixed.

- Include correctness bugs, security problems, data loss hazards, broken migrations, contract violations, and obvious performance regressions on critical paths.
- Include missing tests when the uncovered path is critical enough that merging would be unsafe.
- State the failure mode, who or what is impacted, and the condition that triggers it.

### Nits

Use for low-severity polish that does not block merge.

- Include naming, readability, small consistency issues, minor test cleanup, or comments that would make the code easier to maintain.
- Keep these brief.
- Do not let nits crowd out more important findings.

### Risks

Use for credible uncertainty that is not yet proven to be a blocker.

- Include rollout concerns, edge cases worth validating, unclear deploy ordering, monitoring gaps, assumptions about production data, or partial test coverage in non-critical areas.
- Be explicit that the point is a risk, what evidence suggests it, and how to reduce uncertainty.
- If evidence becomes strong enough to show an actual defect, move it to blocking issues.

## Review Standards

- Prefer source-backed findings. If a concern is mostly speculative, place it under risks instead of blockers.
- Separate design feedback from merge blockers.
- Avoid repeating what the diff already makes obvious.
- Do not invent feedback to fill a category. If a bucket is empty, say `None.`
- Order items by severity within each category.

## Output Format

Use these exact section headings in this order:

### Architectural concerns

- One bullet per finding with file references and concrete reasoning.
- Say `None.` if there is nothing worth calling out.

### Blocking issues

- One bullet per finding with file references, impact, and failure mode.
- Say `None.` if there is nothing merge-blocking.

### Nits

- One bullet per nit.
- Say `None.` if there are no meaningful nits.

### Risks

- One bullet per risk with evidence and the missing validation or mitigation.
- Say `None.` if there are no material risks beyond the listed findings.

Keep any closing summary short. The four categories are the primary output.