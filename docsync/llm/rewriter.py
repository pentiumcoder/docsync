import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from docsync.llm import prompts
from docsync.llm.verifier import StalenessResult
from docsync.parsers.docs_parser import DocSection

if TYPE_CHECKING:
    from openai import OpenAI


@dataclass
class CorrectionResult:
    corrected_content: str
    confidence: float
    changed_parts: list[str]
    requires_human_review: bool
    section_id: str


def _clamp_confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence is not numeric")
    return max(0.0, min(1.0, confidence))


def _issues_text(staleness: StalenessResult) -> str:
    if not staleness.specific_issues:
        return "- (none provided)"
    return "\n".join(f"- {issue}" for issue in staleness.specific_issues)


def _safe_default(section: DocSection) -> CorrectionResult:
    return CorrectionResult(
        corrected_content=section.content,
        confidence=0.4,
        changed_parts=[],
        requires_human_review=True,
        section_id=section.section_id,
    )


def _call_json(
    client: "OpenAI",
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def rewrite_section(
    section: DocSection,
    staleness: StalenessResult,
    code_context: str,
    client: "OpenAI",
    model: str,
    confidence_threshold: float = 0.8,
) -> CorrectionResult:
    issues_text = _issues_text(staleness)

    try:
        rewrite_payload = _call_json(
            client,
            model,
            prompts.REWRITER_SYSTEM_PROMPT,
            prompts.REWRITER_USER_PROMPT.format(
                section_content=section.content,
                code_context=code_context,
                issues=issues_text,
            ),
        )

        corrected_content = rewrite_payload["corrected_content"]
        if not isinstance(corrected_content, str) or not corrected_content.strip():
            raise ValueError("corrected_content must be a non-empty string")

        rewrite_confidence = _clamp_confidence(rewrite_payload["confidence"])

        changed_parts = rewrite_payload["changed_parts"]
        if not isinstance(changed_parts, list) or not all(
            isinstance(part, str) for part in changed_parts
        ):
            raise ValueError("changed_parts must be a list of strings")
    except Exception:
        return _safe_default(section)

    try:
        validation_payload = _call_json(
            client,
            model,
            prompts.VALIDATOR_SYSTEM_PROMPT,
            prompts.VALIDATOR_USER_PROMPT.format(
                section_content=section.content,
                corrected_content=corrected_content,
                issues=issues_text,
            ),
        )

        fixes_issues = validation_payload["fixes_issues"]
        if not isinstance(fixes_issues, bool):
            raise ValueError("fixes_issues must be a boolean")

        validation_confidence = _clamp_confidence(validation_payload["confidence"])

        unintended_changes = validation_payload["unintended_changes"]
        if not isinstance(unintended_changes, list) or not all(
            isinstance(change, str) for change in unintended_changes
        ):
            raise ValueError("unintended_changes must be a list of strings")
    except Exception:
        return CorrectionResult(
            corrected_content=corrected_content,
            confidence=0.4,
            changed_parts=changed_parts,
            requires_human_review=True,
            section_id=section.section_id,
        )

    confidence = min(rewrite_confidence, validation_confidence)
    requires_human_review = (
        not fixes_issues
        or bool(unintended_changes)
        or confidence < confidence_threshold
    )

    return CorrectionResult(
        corrected_content=corrected_content,
        confidence=confidence,
        changed_parts=changed_parts,
        requires_human_review=requires_human_review,
        section_id=section.section_id,
    )
