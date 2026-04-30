from __future__ import annotations

from comet_cc_recall.anchor import build_anchor


def test_full_anchor_shape():
    s = build_anchor(
        repo="myapp",
        file_rel="services/payments.py",
        symbols=["IdempotencyKey", "reserve_key"],
        language="python",
    )
    assert s == (
        "repo:myapp | file:services/payments.py | lang:python | "
        "symbols: IdempotencyKey, reserve_key"
    )


def test_anchor_skips_empty_pieces():
    s = build_anchor(repo=None, file_rel="x.py", symbols=[], language=None)
    assert s == "file:x.py"


def test_anchor_empty_when_all_blank():
    assert build_anchor(repo=None, file_rel="", symbols=[], language=None) == ""


def test_anchor_drops_empty_symbol_strings():
    s = build_anchor(repo="r", file_rel="f.py", symbols=["a", "", None], language=None)
    assert "symbols: a" in s
    assert ", , " not in s
