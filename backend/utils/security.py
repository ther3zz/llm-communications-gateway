import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def _get_fernet():
    salt = os.getenv("SALT", "default_insecure_salt_change_me")
    if salt == "replace_with_long_random_string":
        # Fallback if user didn't change sample
        salt = "fallback_salt_value"
        
    password = b"db_encryption_key" # In a real app, this should be a separate secret too. 
    # For now, we derive the key from the SALT alone effectively, assuming SALT is the secret.
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return Fernet(key)

def encrypt_value(value: str) -> str:
    if not value:
        return value
    
    if os.getenv("ENCRYPTION_ENABLED", "false").lower() != "true":
        return value
        
    try:
        f = _get_fernet()
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        print(f"Encryption error: {e}")
        return value

def decrypt_value(value: str) -> str:
    if not value:
        return value

    if os.getenv("ENCRYPTION_ENABLED", "false").lower() != "true":
        return value

    try:
        f = _get_fernet()
        return f.decrypt(value.encode()).decode()
    except Exception as e:
        # If decryption fails (e.g. invalid token, or not encrypted yet), return original
        # This handles the case where we toggle encryption ON but DB still has plain text.
        return value
