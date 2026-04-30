from __future__ import annotations

from pathlib import Path

from comet_cc_recall.symbols import (
    detect_language,
    extract_from_path,
    extract_symbols,
    join_for_query,
)


def test_detect_language_known_extensions():
    assert detect_language("foo.py") == "python"
    assert detect_language("foo.ts") == "typescript"
    assert detect_language("foo.tsx") == "typescript"
    assert detect_language("foo.js") == "javascript"
    assert detect_language("foo.go") == "go"
    assert detect_language("foo.rs") == "rust"


def test_detect_language_unknown_returns_none():
    assert detect_language("foo.txt") is None
    assert detect_language("README") is None


def test_python_extracts_classes_and_functions(sample_python: Path):
    lang, syms = extract_from_path(sample_python)
    assert lang == "python"
    assert "IdempotencyKey" in syms
    assert "reserve_key" in syms
    assert "release_key" in syms
    # Underscore-prefixed must be filtered.
    assert not any(s.startswith("_") for s in syms)
    # Order: class IdempotencyKey appears before reserve_key in source.
    assert syms.index("IdempotencyKey") < syms.index("reserve_key")


def test_typescript_extracts_class_function_const_iface_type(sample_typescript: Path):
    lang, syms = extract_from_path(sample_typescript)
    assert lang == "typescript"
    for expected in ("User", "Token", "login", "fetchUser", "AuthService"):
        assert expected in syms, f"{expected} missing from {syms}"


def test_go_extracts_func_and_type(sample_go: Path):
    lang, syms = extract_from_path(sample_go)
    assert lang == "go"
    assert "Server" in syms
    assert "NewServer" in syms
    assert "Listen" in syms


def test_top_k_caps_results():
    src = "\n".join(f"def fn_{i}(): pass" for i in range(50))
    syms = extract_symbols(src, "python", top_k=5)
    assert len(syms) == 5
    assert syms == [f"fn_{i}" for i in range(5)]


def test_extract_from_path_unknown_lang_returns_empty(tmp_path: Path):
    p = tmp_path / "notes.txt"
    p.write_text("nothing here")
    lang, syms = extract_from_path(p)
    assert lang is None
    assert syms == []


def test_extract_from_path_missing_file(tmp_path: Path):
    p = tmp_path / "ghost.py"
    lang, syms = extract_from_path(p)
    assert lang == "python"
    assert syms == []


def test_join_for_query_stable():
    assert join_for_query(["a", "b", "c"]) == "a, b, c"
    assert join_for_query([]) == ""


def test_dedupes_repeats():
    src = """
def foo(): pass
def foo(): pass
class Foo: pass
class Foo: pass
"""
    syms = extract_symbols(src, "python")
    assert syms.count("foo") == 1
    assert syms.count("Foo") == 1
