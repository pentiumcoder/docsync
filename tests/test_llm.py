import json
from unittest.mock import MagicMock

import pytest

from docsync.llm import prompts
from docsync.llm.rewriter import CorrectionResult, rewrite_section
from docsync.llm.verifier import StalenessResult, verify_staleness
from docsync.parsers.docs_parser import DocSection

MODEL = "gpt-4o-mini"


def make_section(content="### get_user\n\nReturns a user by ID."):
    return DocSection(
        section_id="docs/api.md##API Reference>get_user",
        file_path="docs/api.md",
        heading_path=["API Reference", "get_user"],
        level=3,
        content=content,
        code_references=["get_user"],
    )


def make_staleness(issues=None):
    return StalenessResult(
        is_stale=True,
        confidence=0.9,
        reason="Signature changed.",
        specific_issues=issues if issues is not None else ["Missing timeout parameter"],
        section_id="docs/api.md##API Reference>get_user",
    )


def make_chat_response(content):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


def make_client(*responses):
    client = MagicMock()
    client.chat.completions.create.side_effect = list(responses)
    return client


def json_response(payload):
    return make_chat_response(json.dumps(payload))


# --- prompts ---


@pytest.mark.parametrize(
    "name",
    [
        "VERIFIER_SYSTEM_PROMPT",
        "VERIFIER_USER_PROMPT",
        "REWRITER_SYSTEM_PROMPT",
        "REWRITER_USER_PROMPT",
        "VALIDATOR_SYSTEM_PROMPT",
        "VALIDATOR_USER_PROMPT",
    ],
)
def test_prompt_constants_are_non_empty_strings(name):
    value = getattr(prompts, name)
    assert isinstance(value, str)
    assert value.strip()


def test_user_prompt_templates_have_expected_placeholders():
    assert "{section_content}" in prompts.VERIFIER_USER_PROMPT
    assert "{code_context}" in prompts.VERIFIER_USER_PROMPT
    assert "{diff}" in prompts.VERIFIER_USER_PROMPT
    assert "{section_content}" in prompts.REWRITER_USER_PROMPT
    assert "{code_context}" in prompts.REWRITER_USER_PROMPT
    assert "{issues}" in prompts.REWRITER_USER_PROMPT
    assert "{corrected_content}" in prompts.VALIDATOR_USER_PROMPT
    assert "{issues}" in prompts.VALIDATOR_USER_PROMPT


# --- verifier ---


def test_verify_staleness_parses_response():
    section = make_section()
    client = make_client(
        json_response(
            {
                "is_stale": True,
                "confidence": 0.92,
                "reason": "The return type changed.",
                "specific_issues": ["Return type is now User, not dict"],
            }
        )
    )

    result = verify_staleness(section, "def get_user(...) -> User:", client, MODEL)

    assert isinstance(result, StalenessResult)
    assert result.is_stale is True
    assert result.confidence == 0.92
    assert result.reason == "The return type changed."
    assert result.specific_issues == ["Return type is now User, not dict"]
    assert result.section_id == section.section_id


def test_verify_staleness_accurate_section():
    client = make_client(
        json_response(
            {
                "is_stale": False,
                "confidence": 0.88,
                "reason": "Documentation matches the code.",
                "specific_issues": [],
            }
        )
    )

    result = verify_staleness(make_section(), "def get_user(): ...", client, MODEL)

    assert result.is_stale is False
    assert result.specific_issues == []


def test_verify_staleness_sends_expected_request():
    client = make_client(
        json_response(
            {
                "is_stale": False,
                "confidence": 0.8,
                "reason": "ok",
                "specific_issues": [],
            }
        )
    )
    section = make_section(content="UNIQUE_SECTION_BODY")
    verify_staleness(section, "UNIQUE_CODE_BODY", client, MODEL, "UNIQUE_DIFF_BODY")

    kwargs = client.chat.completions.create.call_args[1]
    assert kwargs["model"] == MODEL
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][0]["content"] == prompts.VERIFIER_SYSTEM_PROMPT
    assert kwargs["messages"][1]["role"] == "user"
    assert "UNIQUE_SECTION_BODY" in kwargs["messages"][1]["content"]
    assert "UNIQUE_CODE_BODY" in kwargs["messages"][1]["content"]
    assert "UNIQUE_DIFF_BODY" in kwargs["messages"][1]["content"]


def test_verify_staleness_clamps_confidence():
    client = make_client(
        json_response(
            {
                "is_stale": True,
                "confidence": 1.7,
                "reason": "sure",
                "specific_issues": [],
            }
        )
    )
    result = verify_staleness(make_section(), "code", client, MODEL)
    assert result.confidence == 1.0


def test_verify_staleness_invalid_json_falls_back():
    section = make_section()
    client = make_client(make_chat_response("not json at all"))

    result = verify_staleness(section, "code", client, MODEL)

    assert result.is_stale is True
    assert result.confidence == 0.4
    assert result.specific_issues == []
    assert result.section_id == section.section_id
    assert result.reason


def test_verify_staleness_missing_field_falls_back():
    client = make_client(json_response({"is_stale": True, "confidence": 0.9}))
    result = verify_staleness(make_section(), "code", client, MODEL)
    assert result.is_stale is True
    assert result.confidence == 0.4


def test_verify_staleness_invalid_issue_type_falls_back():
    client = make_client(
        json_response(
            {
                "is_stale": True,
                "confidence": 0.9,
                "reason": "bad",
                "specific_issues": "not a list",
            }
        )
    )
    result = verify_staleness(make_section(), "code", client, MODEL)
    assert result.confidence == 0.4
    assert result.specific_issues == []


def test_verify_staleness_api_error_never_raises():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")

    result = verify_staleness(make_section(), "code", client, MODEL)

    assert result.is_stale is True
    assert result.confidence == 0.4
    assert "boom" in result.reason


# --- rewriter ---


def make_rewrite_payload(
    content="### get_user\n\nReturns a user by ID with an optional timeout.",
    confidence=0.9,
    changed_parts=None,
):
    return {
        "corrected_content": content,
        "confidence": confidence,
        "changed_parts": changed_parts if changed_parts is not None else ["Updated signature"],
    }


def make_validation_payload(fixes_issues=True, confidence=0.9, unintended_changes=None):
    return {
        "fixes_issues": fixes_issues,
        "confidence": confidence,
        "unintended_changes": unintended_changes if unintended_changes is not None else [],
    }


def test_rewrite_section_happy_path():
    section = make_section()
    client = make_client(
        json_response(make_rewrite_payload()),
        json_response(make_validation_payload()),
    )

    result = rewrite_section(
        section, make_staleness(), "def get_user(user_id, timeout=None): ...", client, MODEL
    )

    assert isinstance(result, CorrectionResult)
    assert result.corrected_content == make_rewrite_payload()["corrected_content"]
    assert result.confidence == 0.9
    assert result.changed_parts == ["Updated signature"]
    assert result.requires_human_review is False
    assert result.section_id == section.section_id
    assert client.chat.completions.create.call_count == 2


def test_rewrite_section_uses_rewrite_then_validation_prompts():
    section = make_section(content="UNIQUE_ORIGINAL")
    client = make_client(
        json_response(make_rewrite_payload()),
        json_response(make_validation_payload()),
    )
    staleness = make_staleness(issues=["UNIQUE_ISSUE"])

    rewrite_section(section, staleness, "UNIQUE_CODE", client, MODEL)

    first = client.chat.completions.create.call_args_list[0][1]
    second = client.chat.completions.create.call_args_list[1][1]

    assert first["messages"][0]["content"] == prompts.REWRITER_SYSTEM_PROMPT
    assert "UNIQUE_ORIGINAL" in first["messages"][1]["content"]
    assert "UNIQUE_CODE" in first["messages"][1]["content"]
    assert "UNIQUE_ISSUE" in first["messages"][1]["content"]

    assert second["messages"][0]["content"] == prompts.VALIDATOR_SYSTEM_PROMPT
    assert "UNIQUE_ORIGINAL" in second["messages"][1]["content"]
    assert "UNIQUE_ISSUE" in second["messages"][1]["content"]
    assert first["response_format"] == {"type": "json_object"}


def test_rewrite_section_requires_review_when_issues_not_fixed():
    client = make_client(
        json_response(make_rewrite_payload()),
        json_response(make_validation_payload(fixes_issues=False)),
    )
    result = rewrite_section(make_section(), make_staleness(), "code", client, MODEL)
    assert result.requires_human_review is True


def test_rewrite_section_requires_review_on_unintended_changes():
    client = make_client(
        json_response(make_rewrite_payload()),
        json_response(make_validation_payload(unintended_changes=["Removed accurate example"])),
    )
    result = rewrite_section(make_section(), make_staleness(), "code", client, MODEL)
    assert result.requires_human_review is True


def test_rewrite_section_requires_review_when_confidence_below_threshold():
    client = make_client(
        json_response(make_rewrite_payload(confidence=0.6)),
        json_response(make_validation_payload(confidence=0.7)),
    )
    result = rewrite_section(
        make_section(), make_staleness(), "code", client, MODEL, confidence_threshold=0.8
    )
    assert result.confidence == 0.6
    assert result.requires_human_review is True


def test_rewrite_section_accepts_custom_threshold():
    client = make_client(
        json_response(make_rewrite_payload(confidence=0.6)),
        json_response(make_validation_payload(confidence=0.7)),
    )
    result = rewrite_section(
        make_section(), make_staleness(), "code", client, MODEL, confidence_threshold=0.5
    )
    assert result.requires_human_review is False


def test_rewrite_section_invalid_rewrite_json_falls_back_to_original():
    section = make_section(content="ORIGINAL CONTENT")
    client = make_client(make_chat_response("not json"))

    result = rewrite_section(section, make_staleness(), "code", client, MODEL)

    assert result.corrected_content == "ORIGINAL CONTENT"
    assert result.confidence == 0.4
    assert result.changed_parts == []
    assert result.requires_human_review is True
    assert client.chat.completions.create.call_count == 1


def test_rewrite_section_empty_correction_falls_back_to_original():
    section = make_section(content="ORIGINAL CONTENT")
    client = make_client(json_response(make_rewrite_payload(content="   ")))

    result = rewrite_section(section, make_staleness(), "code", client, MODEL)

    assert result.corrected_content == "ORIGINAL CONTENT"
    assert result.requires_human_review is True


def test_rewrite_section_invalid_validation_json_keeps_correction_but_flags():
    client = make_client(
        json_response(make_rewrite_payload(content="CORRECTED")),
        make_chat_response("not json"),
    )

    result = rewrite_section(make_section(), make_staleness(), "code", client, MODEL)

    assert result.corrected_content == "CORRECTED"
    assert result.confidence == 0.4
    assert result.requires_human_review is True


def test_rewrite_section_api_error_never_raises():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")

    result = rewrite_section(make_section(content="ORIGINAL"), make_staleness(), "code", client, MODEL)

    assert result.corrected_content == "ORIGINAL"
    assert result.requires_human_review is True
