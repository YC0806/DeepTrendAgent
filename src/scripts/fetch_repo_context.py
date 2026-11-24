#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from importlib import import_module
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PACKAGE_NAME = PACKAGE_DIR.name

_cli_common = import_module(f"{PACKAGE_NAME}.scripts._cli_common")
models = import_module(f"{PACKAGE_NAME}.models")
tools = import_module(f"{PACKAGE_NAME}.tools")

load_json = _cli_common.load_json
repo_slug_from_full_name = _cli_common.repo_slug_from_full_name
resolve_run_dir = _cli_common.resolve_run_dir
write_json = _cli_common.write_json
RawCommitInfo = models.RawCommitInfo
RawRepoMetadata = models.RawRepoMetadata
RawRepoRelease = models.RawRepoRelease
RawRepoResources = models.RawRepoResources
RawRepoTag = models.RawRepoTag
build_github_repo_context = tools.build_github_repo_context
get_github_repo_default_branch = tools.get_github_repo_default_branch
get_github_repo_last_commit = tools.get_github_repo_last_commit
get_github_repo_metadata = tools.get_github_repo_metadata
get_github_repo_readme = tools.get_github_repo_readme
get_github_repo_releases = tools.get_github_repo_releases
get_github_repo_tags = tools.get_github_repo_tags


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a normalized DeepTrend RepoContext for a single repository."
    )
    parser.add_argument("--repo-full-name", required=True)
    parser.add_argument("--repo-resources-json", help="Bundled RawRepoResources JSON; overrides individual signal flags.")
    parser.add_argument("--repo-metadata-json")
    parser.add_argument("--repo-readme-json")
    parser.add_argument("--repo-releases-json")
    parser.add_argument("--repo-tags-json")
    parser.add_argument("--repo-last-commit-json")
    parser.add_argument("--default-branch")
    parser.add_argument("--run-dir")
    parser.add_argument("--output-path")
    parser.add_argument(
        "--print-only",
        action="store_true",
        default=False,
        help=(
            "Print the context summary to stdout without persisting the JSON. "
            "Required when neither --run-dir nor --output-path is given; "
            "otherwise the script refuses to run to avoid silently dropping "
            "the repo context."
        ),
    )
    parser.add_argument("--readme-limit", type=int, default=3000)
    parser.add_argument("--release-notes-limit", type=int, default=1500)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def _build_from_resources(args: argparse.Namespace, resources_data: dict):
    raw_resources = RawRepoResources.from_dict(resources_data)
    return build_github_repo_context(raw_resources)


def _build_from_layered_signals(args: argparse.Namespace):
    metadata_data = load_json(args.repo_metadata_json)
    metadata = (
        RawRepoMetadata.from_dict(metadata_data)
        if metadata_data is not None
        else get_github_repo_metadata(args.repo_full_name)
    )

    default_branch = args.default_branch or get_github_repo_default_branch(args.repo_full_name)

    readme_data = load_json(args.repo_readme_json)
    if readme_data is not None:
        if isinstance(readme_data, str):
            readme = readme_data
        elif isinstance(readme_data, dict):
            readme = readme_data.get("content")
        else:
            readme = None
    else:
        readme = get_github_repo_readme(args.repo_full_name, ref=default_branch)

    releases_data = load_json(args.repo_releases_json)
    releases = (
        [RawRepoRelease.from_dict(item) for item in releases_data]
        if releases_data is not None
        else get_github_repo_releases(args.repo_full_name)
    )

    tags_data = load_json(args.repo_tags_json)
    tags = (
        [RawRepoTag.from_dict(item) for item in tags_data]
        if tags_data is not None
        else get_github_repo_tags(args.repo_full_name)
    )

    last_commit_data = load_json(args.repo_last_commit_json)
    last_commit = (
        RawCommitInfo.from_dict(last_commit_data)
        if last_commit_data is not None
        else get_github_repo_last_commit(args.repo_full_name, ref=default_branch)
    )

    return build_github_repo_context(
        metadata=metadata,
        readme=readme,
        releases=releases,
        tags=tags,
        last_commit=last_commit,
    )


def main() -> int:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)

    if args.output_path is None and run_dir is None and not args.print_only:
        print(
            "fetch_repo_context failed: no output destination: pass --run-dir <dir>, "
            "--output-path <file>, or --print-only. The DEEPTREND_RUN_DIR env var is "
            "also accepted but is not inherited across separate bash invocations — "
            "prefer --run-dir.",
            file=sys.stderr,
        )
        return 1

    resources_data = load_json(args.repo_resources_json)
    if resources_data is not None:
        repo_context = _build_from_resources(args, resources_data)
    else:
        repo_context = _build_from_layered_signals(args)

    if args.readme_limit and repo_context.readme and len(repo_context.readme) > args.readme_limit:
        repo_context.readme = repo_context.readme[: args.readme_limit] + "\n\n[truncated]"
    if (
        args.release_notes_limit
        and repo_context.release_notes
        and len(repo_context.release_notes) > args.release_notes_limit
    ):
        repo_context.release_notes = repo_context.release_notes[: args.release_notes_limit] + "\n\n[truncated]"

    output_path = args.output_path
    if output_path is None and run_dir is not None:
        repo_slug = repo_slug_from_full_name(args.repo_full_name)
        output_path = str(run_dir / "repo" / f"{repo_slug}.context.json")
    if output_path:
        write_json(output_path, repo_context.to_dict(), pretty=args.pretty)
    print(json.dumps({"repo_full_name": repo_context.repo_full_name, "output_path": output_path}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
