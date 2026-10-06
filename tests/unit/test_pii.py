from pathlib import Path

import pytest

from secure_policy_rag import corpus, pii

# Published example identifiers whose check digits are valid, and the same values with one digit changed.
VALID = {
    "IBAN": ["NL91ABNA0417164300", "NL91 ABNA 0417 1643 00", "DE89 3704 0044 0532 0130 00", "GB82WEST12345698765432"],
    "CARD": ["4111 1111 1111 1111", "5500-0000-0000-0004", "4012888888881881"],
    "TCKN": ["10000000146"],
    "BSN": ["111222333", "123456782", "1112.22.333"],
    "EMAIL": ["j.devries@example.nl", "first.last+tag@sub.bank.example"],
    "PHONE": ["+31 6 1234 5678", "+90 532 123 45 67", "06-12345678", "0532 123 45 67"],
}
INVALID_CHECKSUM = ["NL91ABNA0417164301", "4111 1111 1111 1112", "10000000147", "111222334"]


@pytest.mark.parametrize(("kind", "value"), [(k, v) for k, values in VALID.items() for v in values])
def test_a_valid_identifier_is_found_and_replaced_by_a_typed_placeholder(kind: str, value: str) -> None:
    redacted = pii.redact(f"Please check {value} today.")
    assert redacted.text == f"Please check [{kind}_1] today."
    assert redacted.counts == {kind: 1}


@pytest.mark.parametrize("value", INVALID_CHECKSUM)
def test_a_number_of_the_right_shape_with_a_wrong_check_digit_is_left_alone(value: str) -> None:
    assert pii.find(f"Reference {value} applies.") == []


@pytest.mark.parametrize(
    "text",
    [
        "The limit is EUR 25000000 for 30 days.",
        "Policy 2026-114 was approved on 2026-10-06 at 07:00.",
        "Grade 12 ranges from EUR 71,000 to EUR 94,000.",
        "Alert 2026-0441 had 37 withdrawals in 4 countries; see section 3.2.",
        "Exposure of EUR 412 million, 10 percent of eligible capital.",
    ],
)
def test_amounts_dates_and_reference_numbers_are_not_mistaken_for_personal_data(text: str) -> None:
    assert pii.find(text) == []


def test_the_corpus_has_personal_data_only_in_its_three_worked_examples() -> None:
    documents = corpus.load(Path(__file__).parents[2] / "corpus")
    found = {
        c.id: sorted({f.kind for f in pii.find(c.text)}) for d in documents for c in d.chunks() if pii.find(c.text)
    }
    assert found == {
        "KYC-001#4": ["IBAN", "PHONE", "TCKN"],
        "KYC-003#4": ["BSN", "EMAIL", "IBAN"],
        "AML-001#4": ["CARD"],
    }


def test_an_iban_followed_by_a_capitalised_word_is_still_found() -> None:
    assert pii.redact("Pay NL91 ABNA 0417 1643 00 AND confirm").text == "Pay [IBAN_1] AND confirm"


def test_the_same_value_gets_the_same_placeholder_and_different_values_different_ones() -> None:
    text = "From NL91ABNA0417164300 to GB82WEST12345698765432, then back to NL91 ABNA 0417 1643 00."
    assert pii.redact(text).text == "From [IBAN_1] to [IBAN_2], then back to [IBAN_1]."
    assert pii.redact(text).counts == {"IBAN": 3}


def test_placeholders_survive_a_second_pass_unchanged() -> None:
    once = pii.redact("Mail j.devries@example.nl about 111222333").text
    assert pii.redact(once).text == once


@pytest.mark.parametrize(
    ("check", "value", "expected"),
    [
        (pii.iban_valid, "nl91abna0417164300", True),
        (pii.iban_valid, "NL91ABNA041716430", False),  # one character short
        (pii.luhn_valid, "4111111111111111", True),
        (pii.luhn_valid, "411111111111", False),  # too short to be a card
        (pii.tckn_valid, "00000000146", False),  # a leading zero is never valid
        (pii.bsn_valid, "000000000", False),  # passes the arithmetic, but is not a number anyone holds
    ],
)
def test_check_digit_edge_cases(check: object, value: str, expected: bool) -> None:
    assert callable(check)
    assert check(value) is expected
