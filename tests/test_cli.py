from click.testing import CliRunner

from docsync.cli import main
from docsync.pipeline import CheckResult, IndexResult


def test_help_lists_commands():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "index" in result.output
    assert "check" in result.output


def test_index_command(mocker):
    run_index = mocker.patch(
        "docsync.cli.run_index", return_value=IndexResult(2, 3, 4)
    )

    result = CliRunner().invoke(main, ["index", "repo", "docs"])

    assert result.exit_code == 0
    assert "2 chunks" in result.output
    assert "3 sections" in result.output
    assert "4 links" in result.output
    run_index.assert_called_once_with("repo", "docs")


def test_check_command(mocker):
    check_result = CheckResult(
        sections_checked=1,
        accurate_count=1,
        auto_fixed_count=0,
        flagged_count=0,
        section_results=[],
    )
    run_check = mocker.patch("docsync.cli.run_check", return_value=check_result)

    result = CliRunner().invoke(
        main,
        ["check", "--base-ref", "abc", "--head-ref", "def", "--pr-number", "9"],
    )

    assert result.exit_code == 0
    assert "Checked 1 sections" in result.output
    assert "1 accurate" in result.output
    run_check.assert_called_once_with(
        base_ref="abc", head_ref="def", pr_number=9, dry_run=False
    )


def test_check_command_dry_run_flag(mocker):
    check_result = CheckResult(0, 0, 0, 0, [])
    run_check = mocker.patch("docsync.cli.run_check", return_value=check_result)

    result = CliRunner().invoke(
        main,
        [
            "check",
            "--base-ref",
            "a",
            "--head-ref",
            "b",
            "--pr-number",
            "1",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert run_check.call_args[1]["dry_run"] is True


def test_check_command_exits_zero_on_error(mocker):
    mocker.patch("docsync.cli.run_check", side_effect=RuntimeError("boom"))

    result = CliRunner().invoke(
        main,
        ["check", "--base-ref", "a", "--head-ref", "b", "--pr-number", "1"],
    )

    assert result.exit_code == 0
    combined = result.output + (result.stderr or "")
    assert "docsync check failed: boom" in combined
