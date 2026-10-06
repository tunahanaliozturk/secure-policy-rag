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
    skip = {".venv", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".models"}
    files = [
        p for p in ROOT.rglob("*") if p.suffix in {".md", ".py", ".sql", ".yaml", ".yml"} and not skip & set(p.parts)
    ]
    offenders = [str(p.relative_to(ROOT)) for p in files if EM_DASH in p.read_text(encoding="utf-8")]
    assert offenders == []
