# Contributing to ContainerForge

Thank you for your interest in contributing! ContainerForge is Apache 2.0 licensed and welcomes all contributions.

## Ways to contribute

- **Add a language** — extend `analyzer/source_detector.py` with new `LANGUAGE_FINGERPRINTS` and `FRAMEWORK_PATTERNS`
- **Add a database** — add an entry to `DB_SERVICES` and `DB_SIGNALS` in `generator/db_wirer.py`
- **Add a cloud provider** — implement a new method in `cloud/cloud_deployer.py`
- **Improve Dockerfile templates** — edit `generator/oci_dockerfile_gen.py`
- **Improve K8s defaults** — edit `k8s/k8s_gen.py`
- **Fix a bug** — open an issue first, then a PR
- **Improve docs** — README, docstrings, examples

## Setup

```bash
git clone https://github.com/containerforge/containerforge
cd containerforge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
pip install pytest pytest-cov
```

## Adding a language

1. Add to `LANGUAGE_FINGERPRINTS` in `analyzer/source_detector.py`:
```python
("mylang", ["indicator-file.ext", "another-file"], [".ml"]),
```

2. Add to `FRAMEWORK_PATTERNS`:
```python
"mylang": [
    ("myframework", ["myframework-dep"], ["MyFramework()"]),
],
```

3. Add to `DEFAULT_PORTS`, `VERSION_FILES`, `DEFAULT_VERSIONS`.

4. Add a Dockerfile template to `generator/oci_dockerfile_gen.py`.

5. Add a test fixture to `tests/fixtures/` and a test case to `tests/test_detector.py`.

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=. --cov-report=html
```

## Pull request checklist

- [ ] Tests pass (`pytest tests/`)
- [ ] New features have test coverage
- [ ] `README.md` updated if adding user-facing features
- [ ] `CHANGELOG.md` entry added under `[Unreleased]`
- [ ] Commit messages are descriptive

## Code style

- Black-formatted (`pip install black && black .`)
- Type hints on public functions
- Docstrings on classes and public methods

## Reporting issues

Please open a [GitHub issue](https://github.com/containerforge/containerforge/issues) with:
- ContainerForge version (`containerforge --version`)
- OS + Python version
- Minimal reproduction steps
- The app directory structure (no source needed — just filenames)
