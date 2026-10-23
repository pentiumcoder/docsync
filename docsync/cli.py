import click

from docsync.pipeline import run_check, run_index


@click.group()
def main():
    """Detect stale documentation caused by code changes."""


@main.command()
@click.argument("repo_path")
@click.argument("docs_path")
def index(repo_path, docs_path):
    """Build the documentation index for a repository."""
    result = run_index(repo_path, docs_path)
    click.echo(
        f"Indexed {result.chunks_count} chunks and {result.sections_count} sections "
        f"({result.links_count} links)."
    )


@main.command()
@click.option("--base-ref", required=True, help="Base ref or SHA of the pull request.")
@click.option("--head-ref", required=True, help="Head ref or SHA of the pull request.")
@click.option("--pr-number", required=True, type=int, help="Pull request number.")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report results without posting comments or creating fix PRs.",
)
def check(base_ref, head_ref, pr_number, dry_run):
    """Check a pull request for stale documentation."""
    try:
        result = run_check(
            base_ref=base_ref,
            head_ref=head_ref,
            pr_number=pr_number,
            dry_run=dry_run,
        )
    except Exception as exc:
        click.echo(f"docsync check failed: {exc}", err=True)
        return

    click.echo(
        f"Checked {result.sections_checked} sections: "
        f"{result.accurate_count} accurate, "
        f"{result.auto_fixed_count} auto-fixed, "
        f"{result.flagged_count} flagged."
    )
