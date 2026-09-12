"""Cryptographic Subsystem Test Suite for SmallBook.

Validates:
- AES-256-GCM authenticated encryption and decryption roundtrip across realistic provider API keys.
- Tamper detection: Authenticated tag corruption correctly raises a decryption failure.
- Secure key masking and suffix extraction across OpenAI, Anthropic, Gemini, and Groq prefixes.
"""

import base64

import pytest

from app.core.crypto import (
    decrypt_api_key,
    encrypt_api_key,
    extract_key_last4,
    mask_api_key,
)


def test_crypto_roundtrip():
    """Verifies AES-256-GCM encrypt and decrypt roundtrip preserves original plaintext.

    Pattern:
        - Arrange: Generate a fixed 32-byte master key and a diverse list of provider key strings.
        - Act: Encrypt each key to base64, then decrypt the ciphertext.
        - Assert: Ciphertext differs from plaintext, has non-zero length, and decrypted matches original.
    """
    test_master_key = base64.b64decode(base64.b64encode(b"0" * 32))
    
    test_keys = [
        "gsk_dummy_mock_groq_key_for_testing_purposes_1234567890abcd",
        "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234",
        "AIzaSyDummyGeminiKeyForUnitTestingPurposes12345678",
        "sk-ant-api03-abcdef1234567890",
        "custom-ollama-key-secret-999"
    ]
    
    for key in test_keys:
        encrypted = encrypt_api_key(key, master_key=test_master_key)
        assert encrypted != key
        assert len(encrypted) > 0
        
        decrypted = decrypt_api_key(encrypted, master_key=test_master_key)
        assert decrypted == key


def test_tampered_payload_raises():
    """Verifies that tampering with ciphertext or authentication tag raises an exception.

    Pattern:
        - Arrange: Encrypt a test secret and flip bits in the final byte of the auth tag.
        - Act & Assert: Attempt decryption with the corrupted payload inside pytest.raises(Exception).
    """
    test_master_key = b"A" * 32
    encrypted = encrypt_api_key("sk-test-secret-12345", master_key=test_master_key)
    
    # Tamper with the base64 ciphertext
    raw = bytearray(base64.b64decode(encrypted))
    raw[-1] ^= 0xFF  # corrupt the auth tag
    corrupted_b64 = base64.b64encode(bytes(raw)).decode("utf-8")
    
    with pytest.raises(Exception):
        decrypt_api_key(corrupted_b64, master_key=test_master_key)


def test_key_masking():
    """Verifies that mask_api_key and extract_key_last4 correctly format provider API keys.

    Pattern:
        - Arrange: Sample keys with various provider prefixes (gsk_, sk-proj-, AIza, sk-ant-).
        - Act: Pass keys to mask_api_key and extract_key_last4.
        - Assert: Verify expected masked representations and last-4 suffix matches.
    """
    assert mask_api_key("gsk_1234567890abcdef1234") == "gsk_...1234"
    assert mask_api_key("sk-proj-1234567890abcdef9999") == "sk-proj-...9999"
    assert mask_api_key("AIzaSy1234567890abcdefAAAA") == "AIza...AAAA"
    assert mask_api_key("sk-ant-1234567890abcdefBBBB") == "sk-ant-...BBBB"
    assert mask_api_key("sk-1234567890abcdefCCCC") == "sk-...CCCC"
    assert mask_api_key("") == ""
    assert extract_key_last4("gsk_1234567890abcdef1234") == "1234"
