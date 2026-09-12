"""
Core Infrastructure & Utility Package

Exports foundational singletons, cryptographic helpers, and connection managers
utilized across the SmallBook application backend:
    - Celery task worker instance (`celery_app`)
    - Shared Redis connection client (`get_redis_client`, `reset_redis_client`)
    - Authenticated AES-GCM BYOK credential encryption/decryption utilities
"""

from app.core.celery_app import celery_app
from app.core.redis_client import get_redis_client, reset_redis_client
from app.core.crypto import (
    encrypt_api_key,
    decrypt_api_key,
    mask_api_key,
    extract_key_last4,
    get_master_encryption_key,
)

__all__ = [
    "celery_app",
    "get_redis_client",
    "reset_redis_client",
    "encrypt_api_key",
    "decrypt_api_key",
    "mask_api_key",
    "extract_key_last4",
    "get_master_encryption_key",
]

