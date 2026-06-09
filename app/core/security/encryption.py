import base64
import hashlib
from cryptography.fernet import Fernet
from app.core.config import settings

def get_fernet_key() -> bytes:
    key_hash = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key_hash)

def encrypt_data(data: str) -> str:
    if not data:
        return ""
    f = Fernet(get_fernet_key())
    return f.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    if not encrypted_data:
        return ""
    f = Fernet(get_fernet_key())
    return f.decrypt(encrypted_data.encode()).decode()
