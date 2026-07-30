"""The exam board marking principles block.

Pure-function tests — build_marking_guidelines takes plain strings and returns
one, so none of this needs a database or an AI call.
"""

from app.services.marking_guidelines import (
    BOARD_CAMBRIDGE,
    BOARD_EDEXCEL,
    COMMAND_WORDS,
    FAMILY_GUIDELINES,
    PAPER_GUIDELINES,
    SUBJECT_FAMILY,
    SUBJECT_GUIDELINES,
    build_marking_guidelines,
    normalize_board,
)


def test_normalize_board_matches_the_seeded_board_strings():
    """The five seeded syllabuses use exactly these two spellings."""
    assert normalize_board("Cambridge O Level") == BOARD_CAMBRIDGE
    assert normalize_board("Edexcel IGCSE") == BOARD_EDEXCEL


def test_normalize_board_tolerates_the_variants_a_syllabus_upload_can_produce():
    """exam_board is free text filled from an AI-drafted value on upload, so
    the seeded spellings are a convention rather than a guarantee."""
    assert normalize_board("cambridge") == BOARD_CAMBRIDGE
    assert normalize_board("CAIE") == BOARD_CAMBRIDGE
    assert normalize_board("Cambridge International AS & A Level") == BOARD_CAMBRIDGE
    assert normalize_board("Pearson Edexcel") == BOARD_EDEXCEL
    assert normalize_board("EDEXCEL International GCSE") == BOARD_EDEXCEL


def test_normalize_board_returns_none_rather_than_guessing():
    """An unidentifiable board must get no principles — marking a Cambridge
    script to Edexcel's rules would be worse than marking it to none."""
    assert normalize_board("AQA") is None
    assert normalize_board("OCR GCSE") is None
    assert normalize_board("") is None


def test_unknown_board_produces_no_block():
    assert build_marking_guidelines("AQA", "8461") == ""
    assert build_marking_guidelines("", "") == ""


def test_each_board_gets_its_own_principles():
    cambridge = build_marking_guidelines("Cambridge O Level", "5090")
    edexcel = build_marking_guidelines("Edexcel IGCSE", "4BI1")

    # Cambridge's numbered principles, not Edexcel's prose.
    assert "whole numbers, never fractions" in cambridge
    assert "All candidates receive the same treatment" not in cambridge
    # Edexcel's, including the one line adapted for this platform: their
    # "consult the team leader" is the tutor's review queue here.
    assert "All candidates receive the same treatment" in edexcel
    assert "the tutor decides" in edexcel
    assert "Crossed-out work should be marked" in edexcel


def test_both_boards_carry_the_zero_rule():
    """An unanswered question scores 0 only when the AI is certain it was not
    answered — "I could not find it" is a low-confidence no-mark, never a 0."""
    for board, code in [("Cambridge O Level", "5070"), ("Edexcel IGCSE", "4MA1")]:
        block = build_marking_guidelines(board, code)
        assert "genuinely not answered" in block
        assert "Never score 0 to represent your own uncertainty." in block


def test_subject_block_is_appended_after_the_board_principles(monkeypatch):
    """Subject conventions refine the general rule, so they read last."""
    monkeypatch.setitem(
        SUBJECT_GUIDELINES,
        (BOARD_EDEXCEL, "4MA1"),
        "Edexcel Mathematics A conventions: award method marks for a correct method.",
    )
    block = build_marking_guidelines("Edexcel IGCSE", "4MA1")

    assert "award method marks for a correct method" in block
    assert block.index("All candidates receive the same treatment") < block.index(
        "award method marks"
    )


def test_subject_without_guidelines_still_gets_the_board_principles():
    """A subject with no entry is the normal case while the registry fills up —
    it must not error, and must not lose the board layer."""
    block = build_marking_guidelines("Edexcel IGCSE", "9999-not-a-real-code")
    assert "All candidates receive the same treatment" in block


def test_subject_guidelines_are_keyed_to_a_known_board():
    """A key whose board half is not a board key is unreachable — this catches
    an entry added as ("Edexcel IGCSE", ...) instead of ("edexcel", ...)."""
    for registry in (SUBJECT_GUIDELINES, SUBJECT_FAMILY, FAMILY_GUIDELINES):
        for key in registry:
            assert key[0] in (BOARD_CAMBRIDGE, BOARD_EDEXCEL)
    for board, _code, _paper in PAPER_GUIDELINES:
        assert board in (BOARD_CAMBRIDGE, BOARD_EDEXCEL)


def test_every_seeded_subject_has_guidelines():
    """The five syllabuses in seed/syllabus/ are what the product ships with."""
    for key in [
        (BOARD_CAMBRIDGE, "5070"),
        (BOARD_CAMBRIDGE, "5090"),
        (BOARD_EDEXCEL, "4CH1"),
        (BOARD_EDEXCEL, "4BI1"),
        (BOARD_EDEXCEL, "4MA1"),
    ]:
        assert key in SUBJECT_GUIDELINES


def test_command_words_load_for_cambridge_and_are_absent_for_edexcel():
    """Cambridge's definitions are published and loaded; Edexcel's have not
    been supplied, and the section is omitted rather than borrowing the other
    board's."""
    cambridge = build_marking_guidelines("Cambridge O Level", "5090")
    assert "Cambridge command words" in cambridge
    assert "Suggest: apply knowledge and understanding" in cambridge

    assert BOARD_EDEXCEL not in COMMAND_WORDS
    edexcel = build_marking_guidelines("Edexcel IGCSE", "4BI1")
    assert "Cambridge command words" not in edexcel
    assert "Summarise: select and present the main points" not in edexcel


def test_science_family_reaches_both_cambridge_sciences_only():
    """5070 and 5090 share Cambridge's science rules; Edexcel has no family."""
    for code in ("5070", "5090"):
        assert "Cambridge science marking rules" in build_marking_guidelines(
            "Cambridge O Level", code
        )
    assert "Cambridge science marking rules" not in build_marking_guidelines(
        "Edexcel IGCSE", "4CH1"
    )


def test_layers_are_ordered_general_to_specific(monkeypatch):
    """Each narrower layer reads as refining the one above it."""
    monkeypatch.setitem(
        PAPER_GUIDELINES, (BOARD_CAMBRIDGE, "5070", "paper 2"), "PAPER-LEVEL-MARKER"
    )
    block = build_marking_guidelines("Cambridge O Level", "5070", "Paper 2")

    order = [
        block.index("Cambridge general marking principles"),
        block.index("Cambridge command words"),
        block.index("Cambridge science marking rules"),
        block.index("Cambridge O Level Chemistry 5070"),
        block.index("PAPER-LEVEL-MARKER"),
    ]
    assert order == sorted(order)


def test_paper_layer_needs_a_paper_number_and_tolerates_tutor_typing(monkeypatch):
    """paper_number is free text a tutor typed at upload; homework has none."""
    monkeypatch.setitem(
        PAPER_GUIDELINES, (BOARD_CAMBRIDGE, "5070", "paper 2"), "PAPER-LEVEL-MARKER"
    )
    for typed in ("Paper 2", "paper 2", "  Paper   2 "):
        assert "PAPER-LEVEL-MARKER" in build_marking_guidelines(
            "Cambridge O Level", "5070", typed
        )
    # Homework passes no paper number, and an unknown paper is not an error.
    assert "PAPER-LEVEL-MARKER" not in build_marking_guidelines("Cambridge O Level", "5070")
    assert "PAPER-LEVEL-MARKER" not in build_marking_guidelines(
        "Cambridge O Level", "5070", "Paper 4"
    )


def test_the_mark_scheme_is_declared_the_higher_authority():
    """Subject and paper text is tutor-supplied, so the block must say the
    official scheme wins and a conflict goes to the tutor, not be left to the
    model to work out."""
    block = build_marking_guidelines("Edexcel IGCSE", "4MA1")
    assert "outranks everything here" in block
    assert "supplied by the tutor" in block
    assert "confidence 'low'" in block


def test_removed_claims_are_not_reintroduced():
    """Five rules were audited as wrong and removed (see the plan). This fails
    if one is pasted back in with a later content update."""
    everything = "\n".join(SUBJECT_GUIDELINES.values()).lower()
    assert "worst method" not in everything
    assert "illegal method" not in everything
    assert "water potential" not in everything
    assert "h^2o" not in everything
    assert "yellow to red" not in everything
