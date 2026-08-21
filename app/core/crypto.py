import os
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

load_dotenv()

def get_master_encryption_key() -> bytes:
    """
    Retrieves and validates the 32-byte AES-256 master key from environment variables.
    """
    key_b64 = os.getenv("APP_ENCRYPTION_KEY")
    if not key_b64:
        raise ValueError(
            "APP_ENCRYPTION_KEY environment variable is missing. "
            "Please generate a 32-byte base64-encoded key and add it to your .env file."
        )
    try:
        raw_bytes = base64.b64decode(key_b64.strip())
        if len(raw_bytes) != 32:
            raise ValueError(f"APP_ENCRYPTION_KEY must be exactly 32 bytes, got {len(raw_bytes)} bytes.")
        return raw_bytes
    except Exception as e:
        raise ValueError(f"Invalid APP_ENCRYPTION_KEY base64 format: {str(e)}")


def encrypt_api_key(raw_key: str, master_key: Optional[bytes] = None) -> str:
    """
    Encrypts a plaintext API key using AES-256-GCM authenticated encryption.
    Returns a Base64-encoded string containing (12-byte Nonce + Ciphertext + 16-byte Auth Tag).
    """
    if not raw_key or not raw_key.strip():
        raise ValueError("Cannot encrypt an empty API key.")
    
    key_bytes = master_key or get_master_encryption_key()
    aesgcm = AESGCM(key_bytes)
    
    # 12-byte random nonce for AES-GCM (NIST recommendation)
    nonce = os.urandom(12)
    
    # AESGCM.encrypt automatically appends the 16-byte auth tag to the ciphertext
    ciphertext = aesgcm.encrypt(nonce, raw_key.strip().encode("utf-8"), None)
    
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("utf-8")


def decrypt_api_key(encrypted_payload: str, master_key: Optional[bytes] = None) -> str:
    """
    Decrypts an AES-256-GCM encrypted payload strictly in-memory.
    """
    if not encrypted_payload or not encrypted_payload.strip():
        raise ValueError("Cannot decrypt an empty payload.")
    
    key_bytes = master_key or get_master_encryption_key()
    aesgcm = AESGCM(key_bytes)
    
    raw_payload = base64.b64decode(encrypted_payload.strip())
    if len(raw_payload) < 28:  # 12 nonce + at least 1 byte ciphertext + 16 tag
        raise ValueError("Malformed encrypted payload: payload too short.")
    
    nonce = raw_payload[:12]
    ciphertext = raw_payload[12:]
    
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")


def mask_api_key(raw_key: str) -> str:
    """
    Produces a safe, masked representation of an API key for UI display.
    Example: 'gsk_dummy_mock_groq_key_for_testing_purposes_1234567890abcd' -> 'gsk_...mW8g'
    """
    if not raw_key:
        return ""
    clean = raw_key.strip()
    if len(clean) <= 8:
        return "****" + clean[-2:] if len(clean) >= 2 else "****"
    
    # Check for known prefixes (sk-, gsk_, AIza, etc.)
    prefix = ""
    if clean.startswith("sk-proj-"):
        prefix = "sk-proj-"
    elif clean.startswith("sk-ant-"):
        prefix = "sk-ant-"
    elif clean.startswith("sk-"):
        prefix = "sk-"
    elif clean.startswith("gsk_"):
        prefix = "gsk_"
    elif clean.startswith("AIza"):
        prefix = "AIza"
    else:
        prefix = clean[:4]
    
    last4 = clean[-4:]
    return f"{prefix}...{last4}"


def extract_key_last4(raw_key: str) -> str:
    """Extracts strictly the last 4 characters for indexing / verification."""
    if not raw_key:
        return ""
    clean = raw_key.strip()
    return clean[-4:] if len(clean) >= 4 else clean
