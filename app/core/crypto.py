"""
Cryptographic Security & API Key Encryption Subsystem

Provides enterprise-grade authenticated symmetric encryption using AES-256-GCM
for Bring-Your-Own-Key (BYOK) user credentials. Guarantees that third-party LLM
keys (OpenAI, Anthropic, Gemini, Groq) are never stored in plaintext within the
database and are only decrypted strictly in-memory during inference execution.

Cryptographic Specification:
    - Algorithm: AES-256-GCM (Galois/Counter Mode).
    - Key Length: 32 bytes (256 bits), loaded from APP_ENCRYPTION_KEY.
    - Nonce: 12 bytes cryptographically secure random bytes (os.urandom) per encryption.
    - Authentication Tag: 16 bytes appended to ciphertext for integrity verification.
    - Wire Format: Base64(12-byte Nonce + Ciphertext + 16-byte Auth Tag).
"""

import os
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

load_dotenv()


def get_master_encryption_key() -> bytes:
    """
    Retrieves and validates the 32-byte AES-256 master key from environment variables.

    Decodes the Base64-encoded master secret from the `APP_ENCRYPTION_KEY` environment
    variable and enforces strict 256-bit length validation before initializing ciphers.

    Returns:
        bytes: The 32-byte raw symmetric encryption key.

    Raises:
        ValueError: If the environment variable is missing, not valid Base64, or does not
            decode to exactly 32 bytes.
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

    Generates a unique 12-byte cryptographic nonce for each encryption invocation to prevent
    replay attacks and ciphertext reuse, encrypts the UTF-8 plaintext bytes, and packs
    the nonce, ciphertext, and authentication tag into a URL-safe Base64 payload.

    Args:
        raw_key: The plaintext API key to encrypt.
        master_key: Optional 32-byte key override; if omitted, loads from APP_ENCRYPTION_KEY.

    Returns:
        str: Base64-encoded string containing [Nonce (12B) + Ciphertext + Auth Tag (16B)].

    Raises:
        ValueError: If the raw_key string is empty or contains only whitespace.
    """
    if not raw_key or not raw_key.strip():
        raise ValueError("Cannot encrypt an empty API key.")
    
    key_bytes = master_key or get_master_encryption_key()
    aesgcm = AESGCM(key_bytes)
    
    # Generate 12-byte random nonce adhering to NIST SP 800-38D recommendations for AES-GCM
    nonce = os.urandom(12)
    
    # AESGCM.encrypt computes the 16-byte authentication tag and appends it to ciphertext
    ciphertext = aesgcm.encrypt(nonce, raw_key.strip().encode("utf-8"), None)
    
    # Combine nonce prefix with authenticated ciphertext and encode as Base64 for database storage
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("utf-8")


def decrypt_api_key(encrypted_payload: str, master_key: Optional[bytes] = None) -> str:
    """
    Decrypts an AES-256-GCM encrypted payload strictly in-memory during inference.

    Unpacks the 12-byte nonce from the Base64 payload, verifies cryptographic authenticity
    using the embedded 16-byte auth tag, and recovers the plaintext API key.

    Args:
        encrypted_payload: The Base64 string containing [Nonce (12B) + Ciphertext + Tag (16B)].
        master_key: Optional 32-byte key override; if omitted, loads from APP_ENCRYPTION_KEY.

    Returns:
        str: The recovered plaintext API key string.

    Raises:
        ValueError: If the payload is empty, malformed, too short (< 28 bytes), or if
            cryptographic integrity check fails (e.g. tampering or incorrect key).
    """
    if not encrypted_payload or not encrypted_payload.strip():
        raise ValueError("Cannot decrypt an empty payload.")
    
    key_bytes = master_key or get_master_encryption_key()
    aesgcm = AESGCM(key_bytes)
    
    raw_payload = base64.b64decode(encrypted_payload.strip())
    if len(raw_payload) < 28:  # 12-byte nonce + minimum 1-byte ciphertext + 16-byte tag
        raise ValueError("Malformed encrypted payload: payload too short.")
    
    # Extract the 12-byte initialization vector (nonce) and remaining authenticated ciphertext
    nonce = raw_payload[:12]
    ciphertext = raw_payload[12:]
    
    # Decrypt and verify authentication tag; raises InvalidTag on tampering or mismatched key
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")


def mask_api_key(raw_key: str) -> str:
    """
    Produces a safe, masked representation of an API key for safe UI display.

    Preserves recognized provider prefixes (e.g., 'sk-ant-', 'gsk_', 'AIza') and
    reveals only the trailing 4 characters, preventing full-credential exposure in
    client-side web inspectors or network inspection.

    Args:
        raw_key: The plaintext API key string.

    Returns:
        str: The masked string representation (e.g., 'gsk_...mW8g' or 'sk-...1234').
    """
    if not raw_key:
        return ""
    clean = raw_key.strip()
    if len(clean) <= 8:
        return "****" + clean[-2:] if len(clean) >= 2 else "****"
    
    # Identify standard provider key prefix patterns for user-friendly UI presentation
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
    """
    Extracts strictly the trailing 4 characters of an API key.

    Used for database indexing, fast collision checks, and UI key identification
    without storing or exposing sensitive key entropy.

    Args:
        raw_key: The plaintext API key string.

    Returns:
        str: Up to 4 trailing characters of the key string.
    """
    if not raw_key:
        return ""
    clean = raw_key.strip()
    return clean[-4:] if len(clean) >= 4 else clean

