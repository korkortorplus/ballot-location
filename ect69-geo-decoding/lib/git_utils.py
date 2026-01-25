"""Git subprocess utilities for reading repository history."""

import subprocess
from pathlib import Path


def run_git(repo_path: Path, *args: str) -> str:
    """Run git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def get_commit_list(repo_path: Path, start_commit: str) -> list[str]:
    """
    Get all commit hashes from start_commit to HEAD (inclusive).

    Args:
        repo_path: Path to the git repository
        start_commit: Starting commit hash (inclusive)

    Returns:
        List of commit hashes in reverse chronological order (newest first)
    """
    # Use start_commit^..HEAD to include the start commit
    output = run_git(repo_path, "log", "--format=%H", f"{start_commit}^..HEAD")
    return [line.strip() for line in output.strip().split("\n") if line.strip()]


def get_commit_metadata(repo_path: Path, commit_hash: str) -> dict:
    """
    Get structured metadata for a single commit.

    Returns:
        Dict with: hash, author_name, author_email, timestamp, message, parents, is_merge
    """
    fmt = "%H|%an|%ae|%at|%s|%P"
    output = run_git(repo_path, "log", "-1", f"--format={fmt}", commit_hash)
    parts = output.strip().split("|", 5)

    parents = parts[5].split() if len(parts) > 5 and parts[5] else []

    return {
        "hash": parts[0],
        "author_name": parts[1],
        "author_email": parts[2],
        "timestamp": int(parts[3]),
        "message": parts[4],
        "parents": parents,
        "is_merge": len(parents) > 1,
    }


def get_file_at_commit(repo_path: Path, commit_hash: str, filepath: str) -> str:
    """
    Get file contents at a specific commit.

    Args:
        repo_path: Path to the git repository
        commit_hash: Git commit hash
        filepath: Path to file within the repository

    Returns:
        File contents as string
    """
    return run_git(repo_path, "show", f"{commit_hash}:{filepath}")


def get_diff_stats(
    repo_path: Path, commit1: str, commit2: str, filepath: str
) -> tuple[int, int]:
    """
    Get lines added/deleted between two commits for a file.

    Returns:
        Tuple of (lines_added, lines_deleted)
    """
    try:
        output = run_git(
            repo_path, "diff", "--numstat", f"{commit1}..{commit2}", "--", filepath
        )
        if not output.strip():
            return 0, 0
        parts = output.strip().split()
        # Handle binary files (shows as "-")
        added = int(parts[0]) if parts[0] != "-" else 0
        deleted = int(parts[1]) if parts[1] != "-" else 0
        return added, deleted
    except subprocess.CalledProcessError:
        return 0, 0
