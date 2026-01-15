"""Security utilities for token encryption and authentication"""
from datetime import datetime, timedelta
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext
import jwt

from app.core.config import settings

# JWT settings
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7


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


def create_access_token(user_id: int, email: str) -> str:
    """
    Create a JWT access token for a user.

    Args:
        user_id: The user's database ID
        email: The user's email

    Returns:
        JWT token string
    """
    expire = datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT access token.

    Args:
        token: The JWT token string

    Returns:
        The decoded payload dict, or None if invalid
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
