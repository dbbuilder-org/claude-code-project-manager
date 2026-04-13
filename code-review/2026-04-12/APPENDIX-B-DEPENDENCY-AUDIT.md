# Appendix B: Dependency Audit

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Tool | pip-audit |
| Vulnerabilities Found | 9 in 7 packages |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 3 (tornado CVEs) |
| MEDIUM | 4 (streamlit, pillow, requests, protobuf) |
| LOW | 2 (pip, pygments) |

## Vulnerability Details

### tornado 6.5.4 — 3 vulnerabilities

| CVE | Severity | Fix |
|-----|----------|-----|
| GHSA-78cv-mqj4-43f7 | HIGH | 6.5.5 |
| CVE-2026-31958 | HIGH | 6.5.5 |
| CVE-2026-35536 | HIGH | 6.5.5 |

tornado is a transitive dependency of Streamlit. Not directly pinned in pyproject.toml.

**Remediation:** `pip install tornado>=6.5.5` or upgrade Streamlit to 1.54.0 which pins a fixed version.

### streamlit 1.52.2 — CVE-2026-33682

| Field | Value |
|-------|-------|
| CVE | CVE-2026-33682 |
| Severity | MEDIUM |
| Fix | 1.54.0 |

**Remediation:** `pip install streamlit>=1.54.0` and update `pyproject.toml`.

### requests 2.32.5 — CVE-2026-25645

| Field | Value |
|-------|-------|
| CVE | CVE-2026-25645 |
| Severity | MEDIUM |
| Fix | 2.33.0 |

requests is a transitive dependency (used by httpx/streamlit internally).

**Remediation:** `pip install requests>=2.33.0`

### pillow 12.1.0 — CVE-2026-25990

| Field | Value |
|-------|-------|
| CVE | CVE-2026-25990 |
| Severity | MEDIUM |
| Fix | 12.1.1 |

pillow is a transitive dependency of Streamlit.

**Remediation:** `pip install pillow>=12.1.1`

### protobuf 6.33.4 — CVE-2026-0994

| Field | Value |
|-------|-------|
| CVE | CVE-2026-0994 |
| Severity | MEDIUM |
| Fix | 5.29.6 or 6.33.5 |

protobuf is a transitive dependency.

**Remediation:** `pip install protobuf>=6.33.5`

### pygments 2.19.2 — CVE-2026-4539

| Field | Value |
|-------|-------|
| CVE | CVE-2026-4539 |
| Severity | LOW |
| Fix | 2.20.0 |

pygments is used by Rich for syntax highlighting.

**Remediation:** `pip install pygments>=2.20.0`

### pip 25.3 — CVE-2026-1703

| Field | Value |
|-------|-------|
| CVE | CVE-2026-1703 |
| Severity | LOW |
| Fix | 26.0 |

**Remediation:** `pip install --upgrade pip`

## Unused Direct Dependencies

The following packages are declared in `pyproject.toml` but not imported anywhere in the codebase:

| Package | Declared Version | Actual Usage |
|---------|-----------------|--------------|
| `pydantic` | ≥2.0.0 | Not imported in any `pm/` source file |
| `fastapi` | ≥0.100.0 | Not imported anywhere |
| `uvicorn` | ≥0.23.0 | Not imported anywhere |
| `gitpython` | ≥3.1.0 | Not imported; git called via subprocess |

**Impact:** 4 unnecessary packages add ~40MB install weight and 3 introduce additional CVE surface area.

## Raw pip-audit Output

```
Found 9 known vulnerabilities in 7 packages
Name      Version ID                  Fix Versions
--------- ------- ------------------- -------------
pillow    12.1.0  CVE-2026-25990      12.1.1
pip       25.3    CVE-2026-1703       26.0
protobuf  6.33.4  CVE-2026-0994       5.29.6,6.33.5
pygments  2.19.2  CVE-2026-4539       2.20.0
requests  2.32.5  CVE-2026-25645      2.33.0
streamlit 1.52.2  CVE-2026-33682      1.54.0
tornado   6.5.4   GHSA-78cv-mqj4-43f7 6.5.5
tornado   6.5.4   CVE-2026-31958      6.5.5
tornado   6.5.4   CVE-2026-35536      6.5.5
```
