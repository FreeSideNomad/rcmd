# F012: PyPI Publishing

## Overview

Automate publishing the `commandbus` library to PyPI using GitHub Actions with trusted publishing (OIDC), eliminating the need for long-lived API tokens.

## Goals

1. Publish package to PyPI on tagged releases
2. Use trusted publishing (OIDC) for secure, tokenless authentication
3. Automate version management from git tags
4. Include proper package metadata for PyPI listing

## Implementation

### 1. Package Configuration

Update `pyproject.toml` with PyPI metadata:

```toml
[project]
name = "commandbus"
dynamic = ["version"]
description = "Command Bus abstraction over PostgreSQL + PGMQ"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [
    { name = "Your Name", email = "your@email.com" }
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Framework :: AsyncIO",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Database",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
keywords = ["commandbus", "cqrs", "pgmq", "postgresql", "async"]

[project.urls]
Homepage = "https://github.com/FreeSideNomad/rcmd"
Repository = "https://github.com/FreeSideNomad/rcmd"
Documentation = "https://github.com/FreeSideNomad/rcmd#readme"

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.targets.wheel]
packages = ["src/commandbus"]
```

### 2. GitHub Actions Workflow

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    name: Build distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Required for hatch-vcs

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install build tools
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    name: Publish to PyPI
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # Required for trusted publishing

    steps:
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

### 3. PyPI Trusted Publishing Setup

1. Go to https://pypi.org/manage/account/publishing/
2. Add a new pending publisher:
   - PyPI Project Name: `commandbus`
   - Owner: `FreeSideNomad`
   - Repository: `rcmd`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

3. Create GitHub environment:
   - Go to repository Settings > Environments
   - Create environment named `pypi`
   - Optionally add protection rules (require approval)

### 4. Release Process

```bash
# Create and push a version tag
git tag v0.1.0
git push origin v0.1.0

# GitHub Actions will automatically:
# 1. Build the package
# 2. Publish to PyPI using trusted publishing
```

## User Stories

### S057: Package Metadata Configuration
Configure pyproject.toml with proper metadata for PyPI listing including description, classifiers, and URLs.

**Acceptance Criteria:**
- Package name is `commandbus`
- Version is derived from git tags via hatch-vcs
- All required metadata fields populated
- Classifiers reflect project status

### S058: GitHub Actions Publish Workflow
Create workflow that builds and publishes on version tags.

**Acceptance Criteria:**
- Workflow triggers on `v*` tags only
- Uses trusted publishing (OIDC)
- Builds wheel and source distribution
- Publishes to PyPI

### S059: Trusted Publishing Setup
Configure PyPI trusted publishing for tokenless authentication.

**Acceptance Criteria:**
- Pending publisher configured on PyPI
- GitHub environment `pypi` created
- No API tokens required

## Security Notes

- **Never commit PyPI tokens** to the repository
- Trusted publishing (OIDC) is the recommended approach
- If tokens are accidentally exposed, revoke immediately at https://pypi.org/manage/account/token/
- GitHub environment protection can require manual approval before publishing

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Add PyPI metadata and hatch-vcs |
| `.github/workflows/publish.yml` | New publish workflow |
| `README.md` | Add PyPI badge and install instructions |

## Testing

Before first publish:
```bash
# Build locally to verify
pip install build
python -m build

# Check the built package
pip install dist/commandbus-*.whl
python -c "import commandbus; print(commandbus.__version__)"
```

## References

- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
- [Hatch VCS](https://github.com/ofek/hatch-vcs)
- [GitHub Actions PyPI Publish](https://github.com/pypa/gh-action-pypi-publish)
