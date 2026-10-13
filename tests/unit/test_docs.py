"""Docs that state facts about the code are checked against it, so they cannot drift silently."""

import re
from pathlib import Path

from secure_policy_rag.settings import Settings

ROOT = Path(__file__).parents[2]
EM_DASH = chr(0x2014)  # spelled as a code point so this file does not trip its own test


def test_the_configuration_table_lists_exactly_the_settings_the_code_reads() -> None:
    table = (ROOT / "docs/operations.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `SPR_([A-Z_]+)` \|", table, flags=re.MULTILINE))
    assert documented == {name.upper() for name in Settings.model_fields}


def test_no_markdown_or_python_file_contains_an_em_dash() -> None:
    # Other people's files (installed packages) and build output are not ours to hold to this.
    skip = {".venv", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".models"}
    skip |= {"node_modules", "dist", "coverage", "playwright-report", "test-results", ".lighthouseci"}
    ours = {".md", ".py", ".sql", ".yaml", ".yml", ".ts", ".vue", ".css", ".html", ".conf"}
    files: list[Path] = []
    for directory, subdirectories, names in ROOT.walk():
        subdirectories[:] = [d for d in subdirectories if d not in skip]  # do not descend: node_modules is large
        files += [directory / name for name in names if Path(name).suffix in ours]
    offenders = [str(p.relative_to(ROOT)) for p in files if EM_DASH in p.read_text(encoding="utf-8")]
    assert offenders == []
    assert any(p.suffix == ".vue" for p in files), "the browser console's sources were not scanned"
