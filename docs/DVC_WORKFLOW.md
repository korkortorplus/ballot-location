# DVC Workflow Guide

This guide explains how to work with DVC (Data Version Control) in this project.

## Overview

DVC tracks large data files outside of git, storing only metadata files (`.dvc`) in the repository. The actual data is stored on DagsHub S3.

**File Size Guidelines:**
- **< 5MB**: Can be committed to git (but prefer DVC for data files)
- **> 5MB**: MUST use DVC (enforced by pre-commit hook)
- **Data files** (`.csv`, `.parquet`, `.pkl`, `.gpkg`): Prefer DVC regardless of size

## Initial Setup

After cloning the repository:

```bash
# Install dependencies
uv sync

# Install git hooks (includes large file check)
mise run setup:hooks

# Pull all DVC-tracked files
dvc pull
```

## Adding Large Files to DVC

When you create or download large data files:

### 1. Add to DVC

```bash
# Add a single file
dvc add path/to/large_file.csv

# Add a directory
dvc add path/to/large_directory/
```

This creates a `.dvc` metadata file and updates `.gitignore`.

### 2. Commit the DVC Metadata

```bash
# Stage the .dvc file and .gitignore
git add path/to/large_file.csv.dvc .gitignore

# Commit to git
git commit -m "Add large_file.csv to DVC"
```

### 3. Push to DVC Remote

```bash
# Push data to DagsHub
mise run dvc-push

# Or directly (if credentials configured)
dvc push
```

## Pulling DVC Files

To download DVC-tracked files:

```bash
# Pull all DVC files
dvc pull

# Pull specific file
dvc pull path/to/file.csv.dvc

# Pull specific directory
dvc pull ect66-geo-decoding/outputs/
```

## Working with Data Files

### Normal Workflow

1. **Pull** latest data: `dvc pull`
2. **Work** with the data (modify, create new files)
3. **Add** new/modified files to DVC: `dvc add file.csv`
4. **Commit** .dvc files to git: `git add file.csv.dvc && git commit`
5. **Push** data to remote: `mise run dvc-push`

### Removing Local Copies

After pushing to DVC, you can remove local data files to save space:

```bash
# Remove local data file (keep .dvc metadata)
rm path/to/large_file.csv

# Restore when needed
dvc pull path/to/large_file.csv.dvc
```

## Troubleshooting

### Pre-commit Hook Blocks Large File

If you try to commit a file >5MB, you'll see:

```
ERROR: Cannot commit files larger than 5MB to git
```

**Solution:**
1. Unstage the file: `git reset HEAD <file>`
2. Track with DVC: `dvc add <file>`
3. Commit .dvc file: `git add <file>.dvc .gitignore && git commit`

### Data File Exists But Has .dvc Metadata

This means the file is DVC-tracked but hasn't been pushed/pulled properly.

**Option 1: Remove local file, pull from DVC**
```bash
rm path/to/file.csv
dvc pull
```

**Option 2: Push local file to DVC**
```bash
dvc push
```

### DVC Remote Authentication

The project uses DagsHub S3 as the DVC remote. Credentials are configured via 1Password:

```bash
# Configure DVC remote (uses 1Password)
mise run set_dvc

# Or manually:
dvc remote modify origin --local access_key_id <dagshub-token>
dvc remote modify origin --local secret_access_key <dagshub-token>
```

### Checking DVC Status

```bash
# Check which files have changes
dvc status

# List all DVC-tracked files
find . -name "*.dvc"

# Check if file is DVC-tracked
ls -la path/to/file.csv.dvc
```

## DVC Remote Info

**Primary Remote:** DagsHub S3
- URL: `https://dagshub.com/wasdee/ballot-location.s3`
- Authentication: DagsHub token (via 1Password or manual config)

**Alternative Access:**
- Browse data files directly on DagsHub: https://dagshub.com/wasdee/ballot-location/src/main/data

## Best Practices

1. **Always DVC-track data files** (`.csv`, `.parquet`, `.pkl`, `.gpkg`, etc.)
2. **Push to DVC before pushing git commits** to ensure data is available
3. **Use meaningful commit messages** for .dvc files (describe the data change)
4. **Don't commit secrets** to .dvc files (use environment variables)
5. **Keep .gitignore updated** when adding new DVC files
6. **Test DVC pull** in a separate clone to verify data is accessible

## Common Commands Reference

```bash
# Add file to DVC
dvc add <file>

# Pull all data
dvc pull

# Pull specific file
dvc pull <file>.dvc

# Push all data
mise run dvc-push  # (uses 1Password)
dvc push           # (if credentials configured)

# Check DVC status
dvc status

# Remove local data (keep .dvc)
rm <file>

# Restore from DVC
dvc checkout <file>.dvc

# List DVC remotes
dvc remote list

# Update DVC file (after modifying data)
dvc add <file>  # This updates the .dvc file
git add <file>.dvc
git commit -m "Update <file>"
```

## Advanced: Managing Large Directories

For directories with many files (like shapefiles), DVC can track the entire directory:

```bash
# Track entire directory
dvc add ect66-geo-decoding/shapefiles/

# This creates a single .dvc file for the directory
# ect66-geo-decoding/shapefiles.dvc

# Pull entire directory
dvc pull ect66-geo-decoding/shapefiles.dvc
```

## Need Help?

- **DVC Documentation:** https://dvc.org/doc
- **DagsHub Documentation:** https://dagshub.com/docs
- **Project Issues:** Check `scripts/audit_large_files.py` to find large files not yet tracked
