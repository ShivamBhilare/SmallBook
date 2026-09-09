import pytest
import base64
from app.core.crypto import (
    encrypt_api_key,
    decrypt_api_key,
    mask_api_key,
    extract_key_last4,
)

def test_crypto_roundtrip():
    # Use a dummy 32-byte key
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
    test_master_key = b"A" * 32
    encrypted = encrypt_api_key("sk-test-secret-12345", master_key=test_master_key)
    
    # Tamper with the base64 ciphertext
    raw = bytearray(base64.b64decode(encrypted))
    raw[-1] ^= 0xFF  # corrupt the auth tag
    corrupted_b64 = base64.b64encode(bytes(raw)).decode("utf-8")
    
    with pytest.raises(Exception):
        decrypt_api_key(corrupted_b64, master_key=test_master_key)

def test_key_masking():
    assert mask_api_key("gsk_1234567890abcdef1234") == "gsk_...1234"
    assert mask_api_key("sk-proj-1234567890abcdef9999") == "sk-proj-...9999"
    assert mask_api_key("AIzaSy1234567890abcdefAAAA") == "AIza...AAAA"
    assert mask_api_key("sk-ant-1234567890abcdefBBBB") == "sk-ant-...BBBB"
    assert mask_api_key("sk-1234567890abcdefCCCC") == "sk-...CCCC"
    assert mask_api_key("") == ""
    assert extract_key_last4("gsk_1234567890abcdef1234") == "1234"
