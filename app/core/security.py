"""Security utilities for token encryption and authentication"""
import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from app.core.config import settings


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Fernet encryption instance (lazy initialization)
_fernet: Optional[Fernet] = None


def get_fernet() -> Fernet:
    """Get or create the Fernet encryption instance"""
    global _fernet
    if _fernet is None:
        key = settings.fernet_key
        if not key:
            raise ValueError(
                "FERNET_KEY environment variable not set. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        try:
            _fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid FERNET_KEY: {e}")
    return _fernet


def encrypt_token(token: str) -> str:
    """
    Encrypt a token (e.g., Clio OAuth access/refresh token) using Fernet.

    Args:
        token: The plaintext token to encrypt

    Returns:
        The encrypted token as a string
    """
    if not isinstance(token, str):
        raise TypeError("Token must be a string")
    fernet = get_fernet()
    encrypted = fernet.encrypt(token.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt a Fernet-encrypted token.

    Args:
        encrypted_token: The encrypted token string

    Returns:
        The decrypted plaintext token

    Raises:
        ValueError: If decryption fails (token is invalid or corrupted)
    """
    if not isinstance(encrypted_token, str):
        raise TypeError("Encrypted token must be a string")
    fernet = get_fernet()
    try:
        decrypted = fernet.decrypt(encrypted_token.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Failed to decrypt token. It may be invalid or corrupted.") from e


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def generate_fernet_key() -> str:
    """Generate a new Fernet encryption key"""
    return Fernet.generate_key().decode("utf-8")
