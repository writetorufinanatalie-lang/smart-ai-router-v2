"""Tests for local sensitive-data detection."""

from backend.privacy_shield import PrivacyShield, SensitiveDataType


def test_detects_email_without_returning_the_email_value():
    text = "Please send this to alex.lee@example.com"

    result = PrivacyShield().inspect(text)

    assert result.blocked is True
    assert result.detected_types == (SensitiveDataType.EMAIL.value,)
    assert "alex.lee@example.com" not in repr(result)


def test_detects_phone_number_with_country_code_and_punctuation():
    result = PrivacyShield().inspect("Call me at +1 (415) 555-2671")

    assert result.blocked is True
    assert SensitiveDataType.PHONE_NUMBER.value in result.detected_types


def test_detects_card_like_number():
    result = PrivacyShield().inspect("Card: 4111 1111 1111 1111")

    assert result.blocked is True
    assert result.detected_types == (SensitiveDataType.CARD_LIKE_NUMBER.value,)


def test_detects_multiple_sensitive_data_types():
    result = PrivacyShield().inspect(
        "Email alex@example.com, phone 415-555-2671, card 4111111111111111"
    )

    assert set(result.detected_types) == {
        SensitiveDataType.EMAIL.value,
        SensitiveDataType.PHONE_NUMBER.value,
        SensitiveDataType.CARD_LIKE_NUMBER.value,
    }


def test_does_not_block_ordinary_numbers_and_arithmetic():
    result = PrivacyShield().inspect("Set fan speed to 40 percent; calculate 2 + 2.")

    assert result.blocked is False
    assert result.detected_types == ()
