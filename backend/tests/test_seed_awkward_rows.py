"""The realistic-data CI check's helpers: the cell generator and the count comparison."""

from scripts.seed_awkward_rows import awkward_string, compare_counts


def test_max_variant_fills_the_declared_length_exactly():
    assert len(awkward_string(255, "max", 1)) == 255
    assert len(awkward_string(1, "max", 1)) == 1


def test_no_variant_exceeds_a_short_column():
    for variant in ("max", "unicode", "empty", "dupe_a", "dupe_b"):
        assert len(awkward_string(3, variant, 9)) <= 3


def test_unbounded_text_is_long_and_empty_is_empty():
    assert len(awkward_string(None, "max", 1)) >= 10_000
    assert awkward_string(50, "empty", 1) == ""


def test_dupe_pair_differs_only_by_case_and_whitespace():
    a, b = awkward_string(50, "dupe_a", 1), awkward_string(50, "dupe_b", 2)
    assert a != b and a.lower() == b.strip().lower()


def test_unicode_variant_carries_arabic_and_emoji():
    text = awkward_string(100, "unicode", 1)
    assert "مرحبا" in text and "🧪" in text


def test_compare_counts_fails_on_a_fall_and_allows_a_dropped_or_new_table():
    _, failures = compare_counts({"a": 5, "gone": 3}, {"a": 5, "new": 0})
    assert failures == []
    _, failures = compare_counts({"a": 5}, {"a": 4})
    assert failures == ["a: 5 -> 4"]
