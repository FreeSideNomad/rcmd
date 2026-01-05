# F012: PyPI Publishing - User Stories

## S057: Package Metadata Configuration

**As a** library maintainer
**I want** proper PyPI metadata in pyproject.toml
**So that** users can discover and understand the package on PyPI

### Description

Configure `pyproject.toml` with all required and recommended metadata fields for a professional PyPI listing. Use `hatch-vcs` for automatic version derivation from git tags.

### Acceptance Criteria

- [ ] Package name is `commandbus`
- [ ] Version is dynamically derived from git tags using hatch-vcs
- [ ] Description clearly states the library purpose
- [ ] README.md is used as the long description
- [ ] License is specified (MIT)
- [ ] Python version requirement is >=3.11
- [ ] Author information is populated
- [ ] Classifiers reflect project status and compatibility
- [ ] Keywords aid discoverability
- [ ] Project URLs include homepage, repository, and documentation
- [ ] Build system uses hatchling with hatch-vcs

### Technical Details

Update `pyproject.toml`:

```toml
[project]
name = "commandbus"
dynamic = ["version"]
description = "Command Bus abstraction over PostgreSQL + PGMQ for reliable async command processing"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [
    { name = "FreeSideNomad" }
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Framework :: AsyncIO",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Database",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Typing :: Typed",
]
keywords = ["commandbus", "cqrs", "pgmq", "postgresql", "async", "message-queue"]

[project.urls]
Homepage = "https://github.com/FreeSideNomad/rcmd"
Repository = "https://github.com/FreeSideNomad/rcmd"
Documentation = "https://github.com/FreeSideNomad/rcmd#readme"
Issues = "https://github.com/FreeSideNomad/rcmd/issues"

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.targets.sdist]
include = [
    "/src/commandbus",
]

[tool.hatch.build.targets.wheel]
packages = ["src/commandbus"]
```

### Dependencies

- Add `hatchling` and `hatch-vcs` as build dependencies

### Testing

```bash
# Verify build works locally
pip install build
python -m build

# Check package contents
tar -tzf dist/commandbus-*.tar.gz
unzip -l dist/commandbus-*.whl

# Test installation
pip install dist/commandbus-*.whl
python -c "import commandbus; print(commandbus.__version__)"
```

---

## S058: GitHub Actions Publish Workflow

**As a** library maintainer
**I want** an automated publish workflow
**So that** packages are published to PyPI when I create version tags

### Description

Create a GitHub Actions workflow that triggers on version tags (`v*`), builds the package distribution, and publishes to PyPI using trusted publishing (OIDC).

### Acceptance Criteria

- [ ] Workflow triggers only on tags matching `v*` pattern
- [ ] Workflow builds both wheel and source distribution
- [ ] Built artifacts are uploaded for inspection
- [ ] Publishing uses trusted publishing (OIDC) - no API tokens
- [ ] Workflow requires `pypi` environment for publishing step
- [ ] Publishing step has `id-token: write` permission
- [ ] Workflow uses latest stable action versions

### Technical Details

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
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for hatch-vcs version detection

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install build tools
        run: pip install build

      - name: Build package
        run: python -m build

      - name: List built artifacts
        run: ls -la dist/

      - name: Upload distribution artifacts
        uses: actions/upload-artifact@v4
        with:
          name: python-package-distributions
          path: dist/

  publish-pypi:
    name: Publish to PyPI
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # OIDC token for trusted publishing

    steps:
      - name: Download distribution artifacts
        uses: actions/download-artifact@v4
        with:
          name: python-package-distributions
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

### Testing

1. Create a test tag locally (don't push):
   ```bash
   git tag v0.0.1-test
   ```

2. Verify workflow syntax:
   ```bash
   gh workflow view publish.yml
   ```

3. First real publish:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   gh run watch
   ```

---

## S059: PyPI Trusted Publishing Setup

**As a** library maintainer
**I want** tokenless PyPI authentication
**So that** publishing is secure without managing API tokens

### Description

Configure PyPI trusted publishing (OIDC) to allow GitHub Actions to publish without storing API tokens. This requires configuration on both PyPI and GitHub.

### Acceptance Criteria

- [ ] Pending publisher registered on PyPI for `commandbus` package
- [ ] Publisher configured with correct GitHub repository details
- [ ] GitHub environment `pypi` created in repository settings
- [ ] Environment protection rules configured (optional but recommended)
- [ ] No API tokens stored in repository secrets
- [ ] Documentation updated with publishing instructions

### Technical Details

#### PyPI Configuration

1. Go to https://pypi.org/manage/account/publishing/
2. Add pending publisher with:
   - **PyPI Project Name:** `commandbus`
   - **Owner:** `FreeSideNomad`
   - **Repository:** `rcmd`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`

#### GitHub Configuration

1. Go to repository Settings > Environments
2. Create new environment: `pypi`
3. Configure protection rules (recommended):
   - Required reviewers: Add maintainers
   - Wait timer: 0 minutes (optional delay)
   - Deployment branches: Only `main` or tags

#### README Updates

Add PyPI badge and installation instructions:

```markdown
[![PyPI version](https://badge.fury.io/py/commandbus.svg)](https://badge.fury.io/py/commandbus)
[![Python Versions](https://img.shields.io/pypi/pyversions/commandbus.svg)](https://pypi.org/project/commandbus/)

## Installation

```bash
pip install commandbus
```
```

### Security Notes

- Trusted publishing uses GitHub's OIDC provider
- No long-lived secrets to rotate or leak
- Publishing is tied to specific workflow and environment
- Environment protection adds manual approval gate

### Release Checklist

When creating a new release:

1. Update CHANGELOG.md (if exists)
2. Ensure all tests pass on main
3. Create annotated tag:
   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```
4. Monitor GitHub Actions workflow
5. Verify package on PyPI

---

## Dependencies Between Stories

```
S057 (Package Metadata)
    ↓
S058 (Publish Workflow) ← S059 (Trusted Publishing)
```

- S057 must be completed first (workflow needs proper pyproject.toml)
- S058 and S059 can be done in parallel but both needed for successful publish
