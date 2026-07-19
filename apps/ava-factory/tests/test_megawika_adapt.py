# Solo personal project, no connection to employer, built with public/free-tier only
"""MegaWika adapter — fixtures mirror the ON-BOX verified schema (both layouts)."""
from dottie.datagen.adapters import ADAPTERS
from dottie.datagen.megawika_adapt import adapt_record


def _entry(passage, urls, texts):
    return {"passage": {"text": [passage]}, "source_url": urls, "source_text": texts}


def test_list_layout_multi_source_passes():
    rec = {"article_title": "Battle of X", "entries": [
        _entry("The battle began in 1900.",
               ["https://a.example/1", "https://b.example/2"],
               ["Author A: the battle began in 1900...", "Author B: in 1900 fighting started..."])]}
    out = adapt_record(rec)
    assert out and "# Battle of X" in out["text"]
    assert "[1] https://a.example/1" in out["text"] and "[2] https://b.example/2" in out["text"]
    assert "independently authored" in out["text"]


def test_columnar_layout_normalizes():
    rec = {"article_title": "T", "entries": {
        "passage": [{"text": ["p one"]}, {"text": ["p two"]}],
        "source_url": [["u1", "u2"], ["u3", "u4"]],
        "source_text": [["s1", "s2"], ["s3", "s4"]]}}
    out = adapt_record(rec)
    assert out and out["text"].count("SOURCES") == 2


def test_single_source_entries_dropped():
    # one cited source is not cross-validation — the doctrine's whole point
    rec = {"entries": [_entry("claim", ["u"], ["only one author"])]}
    assert adapt_record(rec) is None


def test_registered_and_garbage_safe():
    assert "megawika" in ADAPTERS
    assert adapt_record({}) is None
    assert adapt_record({"entries": "not-a-structure"}) is None
