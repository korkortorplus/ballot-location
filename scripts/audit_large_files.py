#!/usr/bin/env python3
"""
Large File Audit Script for DVC-tracked repositories

Scans the repository for large files, checks their DVC tracking status,
and generates a comprehensive report.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def get_file_size(file_path: Path) -> int:
    """Get file size in bytes"""
    try:
        return file_path.stat().st_size
    except (OSError, FileNotFoundError):
        return 0


def is_dvc_tracked(file_path: Path) -> bool:
    """Check if file has corresponding .dvc metadata file"""
    dvc_file = Path(str(file_path) + '.dvc')
    return dvc_file.exists()


def is_git_ignored(file_path: Path, repo_root: Path) -> bool:
    """Check if file is git-ignored"""
    try:
        result = subprocess.run(
            ['git', 'check-ignore', '-q', str(file_path)],
            cwd=repo_root,
            capture_output=True
        )
        # Exit code 0 means file is ignored
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False


def is_git_staged(file_path: Path, repo_root: Path) -> bool:
    """Check if file is currently staged in git"""
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only'],
            cwd=repo_root,
            capture_output=True,
            text=True
        )
        staged_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        rel_path = file_path.relative_to(repo_root)
        return str(rel_path) in staged_files
    except (subprocess.CalledProcessError, ValueError):
        return False


def scan_large_files(repo_root: Path, threshold_bytes: int) -> List[Tuple[Path, int, bool, bool, bool]]:
    """
    Scan repository for large files

    Returns: List of tuples (file_path, size, is_dvc_tracked, is_staged, is_ignored)
    """
    large_files = []

    # Scan all files in the repository
    for file_path in repo_root.rglob('*'):
        # Skip directories
        if not file_path.is_file():
            continue

        # Skip .git directory
        if '.git' in file_path.parts:
            continue

        # Skip .dvc files themselves
        if file_path.suffix == '.dvc':
            continue

        # Check file size
        file_size = get_file_size(file_path)
        if file_size > threshold_bytes:
            dvc_tracked = is_dvc_tracked(file_path)
            staged = is_git_staged(file_path, repo_root)
            ignored = is_git_ignored(file_path, repo_root)

            large_files.append((file_path, file_size, dvc_tracked, staged, ignored))

    # Sort by size (descending)
    large_files.sort(key=lambda x: x[1], reverse=True)

    return large_files


def check_unpushed_commits(repo_root: Path, threshold_bytes: int) -> List[Tuple[str, str, int]]:
    """
    Check unpushed commits for large files

    Returns: List of tuples (commit_hash, file_path, size)
    """
    large_files_in_commits = []

    try:
        # Get list of unpushed commits
        result = subprocess.run(
            ['git', 'log', 'origin/main..HEAD', '--pretty=format:%H'],
            cwd=repo_root,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return large_files_in_commits

        commit_hashes = result.stdout.strip().split('\n') if result.stdout.strip() else []

        for commit_hash in commit_hashes:
            # List files in commit with sizes
            result = subprocess.run(
                ['git', 'ls-tree', '-r', '-l', commit_hash],
                cwd=repo_root,
                capture_output=True,
                text=True
            )

            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                parts = line.split()
                if len(parts) >= 5:
                    size_str = parts[3]
                    file_path = ' '.join(parts[4:])

                    # Skip if size is '-' (directory or submodule)
                    if size_str == '-':
                        continue

                    try:
                        size = int(size_str)
                        if size > threshold_bytes:
                            large_files_in_commits.append((commit_hash[:7], file_path, size))
                    except ValueError:
                        continue

    except subprocess.CalledProcessError:
        pass

    return large_files_in_commits


def format_size(size_bytes: int) -> str:
    """Format size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def generate_report(
    repo_root: Path,
    large_files: List[Tuple[Path, int, bool, bool, bool]],
    unpushed_large_files: List[Tuple[str, str, int]],
    threshold_bytes: int,
    format_type: str = 'markdown'
) -> str:
    """Generate audit report"""

    if format_type == 'markdown':
        report = []
        report.append("# Large File Audit Report")
        report.append("")
        report.append(f"**Threshold:** {format_size(threshold_bytes)}")
        report.append(f"**Repository:** {repo_root}")
        report.append("")

        # Summary
        report.append("## Summary")
        report.append("")
        total_large = len(large_files)
        dvc_tracked_count = sum(1 for _, _, dvc, _, _ in large_files if dvc)
        not_tracked_count = sum(1 for _, _, dvc, _, _ in large_files if not dvc)
        staged_count = sum(1 for _, _, _, staged, _ in large_files if staged)

        report.append(f"- **Total large files:** {total_large}")
        report.append(f"- **DVC-tracked:** {dvc_tracked_count}")
        report.append(f"- **NOT DVC-tracked:** {not_tracked_count}")
        report.append(f"- **Staged in git:** {staged_count}")
        report.append(f"- **Large files in unpushed commits:** {len(unpushed_large_files)}")
        report.append("")

        # Large files in unpushed commits
        if unpushed_large_files:
            report.append("## ⚠️  Large Files in Unpushed Commits")
            report.append("")
            report.append("| Commit | File | Size |")
            report.append("|--------|------|------|")
            for commit, file_path, size in unpushed_large_files:
                report.append(f"| `{commit}` | `{file_path}` | {format_size(size)} |")
            report.append("")
        else:
            report.append("## ✓ Unpushed Commits Check")
            report.append("")
            report.append("No large files found in unpushed commits.")
            report.append("")

        # Files not DVC-tracked
        not_tracked = [(p, s, staged, ignored) for p, s, dvc, staged, ignored in large_files if not dvc]
        if not_tracked:
            report.append("## ⚠️  Large Files NOT DVC-Tracked")
            report.append("")
            report.append("These files should be tracked with DVC:")
            report.append("")
            report.append("| File | Size | Staged | Git-Ignored |")
            report.append("|------|------|--------|-------------|")
            for file_path, size, staged, ignored in not_tracked:
                rel_path = file_path.relative_to(repo_root)
                staged_str = "✓" if staged else ""
                ignored_str = "✓" if ignored else ""
                report.append(f"| `{rel_path}` | {format_size(size)} | {staged_str} | {ignored_str} |")
            report.append("")
            report.append("**Action required:**")
            report.append("```bash")
            for file_path, _, _, _ in not_tracked:
                rel_path = file_path.relative_to(repo_root)
                report.append(f"dvc add {rel_path}")
            report.append("```")
            report.append("")

        # Files with .dvc but data file exists
        dvc_tracked = [(p, s) for p, s, dvc, _, _ in large_files if dvc]
        if dvc_tracked:
            report.append("## ℹ️  DVC-Tracked Files (Data File Exists Locally)")
            report.append("")
            report.append("These files have .dvc metadata but the actual data file still exists locally.")
            report.append("This is normal if you're actively working with the data.")
            report.append("")
            report.append("| File | Size |")
            report.append("|------|------|")
            for file_path, size in dvc_tracked:
                rel_path = file_path.relative_to(repo_root)
                report.append(f"| `{rel_path}` | {format_size(size)} |")
            report.append("")
            report.append("**To remove local copies after pushing to DVC:**")
            report.append("```bash")
            for file_path, _ in dvc_tracked:
                rel_path = file_path.relative_to(repo_root)
                report.append(f"rm {rel_path}")
            report.append("```")
            report.append("")

        # All large files
        if large_files:
            report.append("## Complete List of Large Files")
            report.append("")
            report.append("| File | Size | DVC | Staged | Ignored |")
            report.append("|------|------|-----|--------|---------|")
            for file_path, size, dvc, staged, ignored in large_files:
                rel_path = file_path.relative_to(repo_root)
                dvc_str = "✓" if dvc else "❌"
                staged_str = "✓" if staged else ""
                ignored_str = "✓" if ignored else ""
                report.append(f"| `{rel_path}` | {format_size(size)} | {dvc_str} | {staged_str} | {ignored_str} |")
            report.append("")

        return '\n'.join(report)

    else:  # plain text
        report = []
        report.append("=" * 80)
        report.append("LARGE FILE AUDIT REPORT")
        report.append("=" * 80)
        report.append(f"Threshold: {format_size(threshold_bytes)}")
        report.append(f"Repository: {repo_root}")
        report.append("")

        for file_path, size, dvc, staged, ignored in large_files:
            rel_path = file_path.relative_to(repo_root)
            status = "DVC-tracked" if dvc else "NOT DVC-tracked"
            staged_str = " [STAGED]" if staged else ""
            ignored_str = " [IGNORED]" if ignored else ""
            report.append(f"{rel_path}: {format_size(size)} - {status}{staged_str}{ignored_str}")

        return '\n'.join(report)


def main():
    parser = argparse.ArgumentParser(
        description='Audit large files in a DVC-tracked repository'
    )
    parser.add_argument(
        '--threshold',
        type=int,
        default=5242880,  # 5MB
        help='File size threshold in bytes (default: 5MB = 5242880)'
    )
    parser.add_argument(
        '--format',
        choices=['markdown', 'plain'],
        default='markdown',
        help='Output format (default: markdown)'
    )
    parser.add_argument(
        '--repo-root',
        type=Path,
        default=Path.cwd(),
        help='Repository root directory (default: current directory)'
    )

    args = parser.parse_args()

    repo_root = args.repo_root.resolve()

    # Check if we're in a git repository
    if not (repo_root / '.git').exists():
        print("Error: Not a git repository", file=sys.stderr)
        sys.exit(1)

    # Scan for large files
    large_files = scan_large_files(repo_root, args.threshold)

    # Check unpushed commits
    unpushed_large_files = check_unpushed_commits(repo_root, args.threshold)

    # Generate report
    report = generate_report(
        repo_root,
        large_files,
        unpushed_large_files,
        args.threshold,
        args.format
    )

    print(report)

    # Exit with non-zero if issues found
    not_tracked = sum(1 for _, _, dvc, _, _ in large_files if not dvc)
    if not_tracked > 0 or len(unpushed_large_files) > 0:
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
