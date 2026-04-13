# Appendix B: Dependency Audit — Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Tool | pip / manual review (no pip-audit installed) |

## Runtime Dependencies

| Package | Version | Status | Notes |
|---------|---------|--------|-------|
| click | 8.3.1 | ✅ Current | Stable |
| rich | 14.2.0 | ✅ Current | Stable |
| pydantic | 2.12.5 | ✅ Current | v2 API |
| pydantic-core | 2.41.5 | ✅ Current | |
| sqlalchemy | 2.x | ✅ Current | |
| fastapi | 0.128.0 | ⚠️ Unused | Declared in pyproject.toml, never imported |
| uvicorn | 0.23.0+ | ⚠️ Unused | Declared in pyproject.toml, never imported |
| streamlit | 1.52.2 | ✅ Current | Dashboard |
| python-dateutil | 2.x | ✅ Stable | |
| gitpython | 3.x | ⚠️ Unused | Declared but `subprocess` used for git instead |

## Development Dependencies

| Package | Version | Status |
|---------|---------|--------|
| pytest | 7.x | ✅ |
| pytest-cov | 4.x | ✅ |

## Issues

### DEP-001: Declared but unused dependencies (LOW)
`fastapi`, `uvicorn`, and `gitpython` appear in `pyproject.toml` but are never imported in source code. `pm/api/__init__.py` is an empty file — the FastAPI surface was never built. These add unnecessary installation weight (~15MB).

**Recommendation:** Remove `fastapi`, `uvicorn`, `gitpython` from `pyproject.toml` dependencies. Move to `[project.optional-dependencies]` if future plans call for them.

### DEP-002: No pinned versions in pyproject.toml (LOW)
All dependencies use `>=` bounds with no upper cap. This allows major version bumps to silently break the install.

**Recommendation:** Pin to compatible-release (`~=`) or add upper bounds for critical packages: `click~=8.0`, `sqlalchemy~=2.0`, `streamlit~=1.52`.

### DEP-003: No lock file (MEDIUM)
No `requirements.txt` or `pip.lock` file exists. Installs across machines may differ.

**Recommendation:** Generate `requirements.txt` via `pip freeze > requirements.txt` and commit it. Or adopt `pip-tools` for deterministic installs.
