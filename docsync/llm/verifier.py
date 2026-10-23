import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from docsync.llm import prompts
from docsync.parsers.docs_parser import DocSection

if TYPE_CHECKING:
    from openai import OpenAI


@dataclass
class StalenessResult:
    is_stale: bool
    confidence: float
    reason: str
    specific_issues: list[str]
    section_id: str


def _clamp_confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence is not numeric")
    return max(0.0, min(1.0, confidence))


def _safe_default(section: DocSection, reason: str) -> StalenessResult:
    return StalenessResult(
        is_stale=True,
        confidence=0.4,
        reason=reason,
        specific_issues=[],
        section_id=section.section_id,
    )


def verify_staleness(
    section: DocSection,
    code_context: str,
    client: "OpenAI",
    model: str,
    diff: str = "",
) -> StalenessResult:
    user_prompt = prompts.VERIFIER_USER_PROMPT.format(
        section_content=section.content,
        code_context=code_context,
        diff=diff,
    )
    messages = [
        {"role": "system", "content": prompts.VERIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        payload = json.loads(response.choices[0].message.content)

        is_stale = payload["is_stale"]
        if not isinstance(is_stale, bool):
            raise ValueError("is_stale must be a boolean")

        confidence = _clamp_confidence(payload["confidence"])

        reason = payload["reason"]
        if not isinstance(reason, str):
            raise ValueError("reason must be a string")

        specific_issues = payload["specific_issues"]
        if not isinstance(specific_issues, list) or not all(
            isinstance(issue, str) for issue in specific_issues
        ):
            raise ValueError("specific_issues must be a list of strings")

        return StalenessResult(
            is_stale=is_stale,
            confidence=confidence,
            reason=reason,
            specific_issues=specific_issues,
            section_id=section.section_id,
        )
    except Exception as exc:
        return _safe_default(section, f"Verifier failed: {exc}")
