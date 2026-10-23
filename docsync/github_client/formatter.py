from dataclasses import dataclass
from typing import Literal

from docsync.llm.rewriter import CorrectionResult
from docsync.parsers.docs_parser import DocSection


@dataclass
class SectionResult:
    section_id: str
    status: Literal["accurate", "auto-fixed", "flagged"]
    fix_pr_url: str | None
    issues: list[str]


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def format_section_result(result: SectionResult) -> str:
    if result.status == "accurate":
        return f"- `{result.section_id}` — accurate"
    if result.status == "auto-fixed":
        if result.fix_pr_url:
            return f"- `{result.section_id}` — auto-fixed in {result.fix_pr_url}"
        return f"- `{result.section_id}` — auto-fixed"
    details = "; ".join(result.issues) if result.issues else "no details provided"
    return f"- `{result.section_id}` — flagged for review: {details}"


def format_pr_comment(results: list[SectionResult]) -> str:
    total = len(results)
    accurate = sum(1 for result in results if result.status == "accurate")
    auto_fixed = sum(1 for result in results if result.status == "auto-fixed")
    flagged = sum(1 for result in results if result.status == "flagged")

    lines = [
        "## DocSync documentation check",
        "",
        f"Checked **{total}** affected documentation section(s): "
        f"**{accurate}** accurate, **{auto_fixed}** auto-fixed, "
        f"**{flagged}** flagged for review.",
    ]

    if not results:
        lines.extend(["", "No affected documentation sections were found."])
        return "\n".join(lines)

    lines.extend(["", "| Section | Status | Details |", "| --- | --- | --- |"])
    for result in results:
        if result.status == "auto-fixed":
            details = result.fix_pr_url or ""
        elif result.status == "flagged":
            details = "; ".join(result.issues)
        else:
            details = ""
        lines.append(
            f"| `{_escape(result.section_id)}` | {result.status} | {_escape(details)} |"
        )
    return "\n".join(lines)


def format_fix_pr_body(
    corrections: list[CorrectionResult],
    sections: list[DocSection],
) -> str:
    section_by_id = {section.section_id: section for section in sections}
    lines = [
        "This PR updates documentation that DocSync detected as stale after recent code changes.",
        "",
        "## Sections updated",
    ]

    for correction in corrections:
        section = section_by_id.get(correction.section_id)
        location = f" (`{section.file_path}`)" if section else ""
        lines.extend(["", f"### `{correction.section_id}`{location}"])
        if correction.changed_parts:
            for part in correction.changed_parts:
                lines.append(f"- {part}")
        else:
            lines.append("- Updated to match the current implementation.")

    return "\n".join(lines)


def format_no_index_comment() -> str:
    return (
        "## DocSync documentation check\n\n"
        "No documentation index was found at `.docsync/`. "
        "Run `docsync index <repo_path> <docs_path>` and commit the generated "
        "`.docsync/` directory to enable documentation checks."
    )
