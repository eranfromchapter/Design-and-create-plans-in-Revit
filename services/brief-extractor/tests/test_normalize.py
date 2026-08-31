"""Normalization: timestamps/filler stripped, chitchat dropped conservatively,
domain content always kept."""

from __future__ import annotations

from brief_extractor.normalize import normalize_transcript


def test_timestamps_and_filler_stripped():
    raw = "[00:12:34] CLIENT: Um, we want, uh, three bedrooms.\n(10:32 AM) DESIGNER: Noted."
    result = normalize_transcript(raw)
    assert "[00:12:34]" not in result.text
    assert "(10:32 AM)" not in result.text
    assert "Um" not in result.text and "uh," not in result.text
    assert "three bedrooms" in result.text


def test_pure_chitchat_dropped_domain_kept():
    raw = (
        "CLIENT: Hi!\nDESIGNER: Good morning!\n"
        "CLIENT: We want an open kitchen.\nCLIENT: Thanks so much!"
    )
    result = normalize_transcript(raw)
    assert "open kitchen" in result.text
    assert "Good morning" not in result.text
    assert result.dropped_lines == 3


def test_when_unsure_keep():
    # greeting-shaped but carrying domain content must be kept
    raw = "CLIENT: Thanks — and yes, keep the kitchen island."
    result = normalize_transcript(raw)
    assert "kitchen island" in result.text
    assert result.dropped_lines == 0


def test_scrub_happens_inside_normalize():
    raw = "CLIENT: Email me at someone@example.com about the bathroom."
    result = normalize_transcript(raw)
    assert "someone@example.com" not in result.text
    assert "[EMAIL_1]" in result.text
    assert result.scrub.counts["email"] == 1
