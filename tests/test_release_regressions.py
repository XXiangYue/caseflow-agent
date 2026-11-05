import json, csv, copy
from caseflow_agent.common import append_jsonl, read_jsonl, freeze
from caseflow_agent.model import estimate_tokens


def test_physical_jsonl_preserves_unicode_line_separators(tmp_path):
    value = {"text": "first\u0085second\u2028third\u2029fourth"}
    path = tmp_path / "rows.jsonl"
    append_jsonl(path, value)
    append_jsonl(path, {"other": True})
    assert read_jsonl(path) == [value, {"other": True}]

def test_untrusted_special_token_marker_is_plain_text():
    assert estimate_tokens("literal <|endoftext|> inside user data") > 0

def test_frozen_json_types_round_trip_without_weakening_change_detection(tmp_path):
    a = freeze(tmp_path / "protocol", {"names": ("a", "b")})
    assert freeze(tmp_path / "protocol", {"names": ["a", "b"]}) == a
    import pytest

    with pytest.raises(ValueError):
        freeze(tmp_path / "protocol", {"names": ["different"]})