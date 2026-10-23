VERIFIER_SYSTEM_PROMPT = (
    "You are a strict but fair documentation accuracy reviewer. You decide whether a "
    "markdown documentation section contains statements that are contradicted by the "
    "current implementation.\n\n"
    "Rules:\n"
    "- Omissions are not staleness. Documentation may summarize behavior and does not "
    "need to mention parameters, return types, private helpers, internal strategies, "
    "retries, or other implementation details it never claims to cover.\n"
    "- Set is_stale to true only when the changed code in the diff makes an existing "
    "statement in the documentation false, misleading, or obsolete. Quote the "
    "documentation claim and the contradicting code in specific_issues.\n"
    "- The code excerpt and diff may be partial. Do not flag behavior that lies outside "
    "the excerpt, and do not flag pre-existing gaps that the diff does not touch.\n"
    "- Prefer is_stale=false when the documentation remains true, even if it is "
    "incomplete.\n"
    "- When is_stale is false, specific_issues must be an empty array.\n"
    "- Be conservative about confidence.\n\n"
    "Respond ONLY with a JSON object matching this schema: "
    '{"is_stale": boolean, "confidence": number between 0 and 1, "reason": string, '
    '"specific_issues": array of strings}.'
)

VERIFIER_USER_PROMPT = (
    "Documentation section:\n---\n{section_content}\n---\n\n"
    "Current code excerpt:\n---\n{code_context}\n---\n\n"
    "Pull request diff:\n---\n{diff}\n---\n\n"
    "Does any statement in the documentation contradict the changed code in the diff? "
    "Report only concrete contradictions caused by this diff, not undocumented details "
    "or pre-existing gaps. If the section is still true, set is_stale to false with an "
    "empty specific_issues array."
)

REWRITER_SYSTEM_PROMPT = (
    "You are a precise technical writer. You correct stale markdown documentation so it "
    "matches the current code. Change only what is necessary and preserve all accurate "
    "content, formatting, and heading structure. Respond ONLY with a JSON object matching "
    'this schema: {"corrected_content": string, "confidence": number between 0 and 1, '
    '"changed_parts": array of strings}. corrected_content must be the full corrected '
    "markdown section, including its heading line."
)

REWRITER_USER_PROMPT = (
    "Documentation section to correct:\n---\n{section_content}\n---\n\n"
    "Current code:\n---\n{code_context}\n---\n\n"
    "Known issues to fix:\n{issues}\n\n"
    "Return the corrected section and a short description of each changed part."
)

VALIDATOR_SYSTEM_PROMPT = (
    "You are a documentation quality reviewer. You check whether a proposed correction "
    "fixes the listed issues without introducing new inaccuracies or removing accurate "
    "information. Respond ONLY with a JSON object matching this schema: "
    '{"fixes_issues": boolean, "confidence": number between 0 and 1, '
    '"unintended_changes": array of strings}.'
)

VALIDATOR_USER_PROMPT = (
    "Original documentation section:\n---\n{section_content}\n---\n\n"
    "Proposed correction:\n---\n{corrected_content}\n---\n\n"
    "Issues that had to be fixed:\n{issues}\n\n"
    "Does the proposed correction fix these issues without unintended changes?"
)
