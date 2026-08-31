"""SI-11: seeded names/emails/addresses/phones are redacted deterministically.
All PII here is synthetic."""

from __future__ import annotations

from brief_extractor.pii import scrub_pii


def test_email_phone_address_name_all_redacted():
    raw = (
        "CLIENT: I'm Jane Placeholder, reach me at jane.placeholder@example.com "
        "or 212-555-0187. The apartment is 245 West 98th Street, Apt 12B."
    )
    result = scrub_pii(raw, client_names=["Jane Placeholder"])
    assert "jane.placeholder@example.com" not in result.text
    assert "212-555-0187" not in result.text
    assert "245 West 98th Street" not in result.text
    assert "Jane Placeholder" not in result.text
    assert "[EMAIL_1]" in result.text
    assert "[PHONE_1]" in result.text
    assert "[ADDRESS_1]" in result.text
    assert "[NAME_1]" in result.text
    assert result.counts == {"email": 1, "phone": 1, "address": 1, "name": 1}


def test_same_value_same_token_and_determinism():
    raw = "Call 212-555-0187 today. Again: 212-555-0187. Or (917) 555-0102."
    a = scrub_pii(raw)
    b = scrub_pii(raw)
    assert a.text == b.text
    assert a.text.count("[PHONE_1]") == 2
    assert "[PHONE_2]" in a.text


def test_honorific_names_without_a_list():
    result = scrub_pii("DESIGNER: Mrs. Placeholder wants a bigger kitchen.")
    assert "Placeholder" not in result.text
    assert "[NAME_1]" in result.text


def test_renovation_quantities_are_not_phones_or_addresses():
    raw = (
        "We want 3 bedrooms, a 2700 mm ceiling, roughly 75 square meters, "
        "and the budget is 250000 dollars. Walls are 100 thick."
    )
    result = scrub_pii(raw)
    assert result.text == raw
    assert result.counts == {}


def test_case_insensitive_client_names():
    result = scrub_pii("jane placeholder said yes.", client_names=["Jane Placeholder"])
    assert "jane placeholder" not in result.text.lower() or "[NAME_1]" in result.text
    assert "[NAME_1]" in result.text
