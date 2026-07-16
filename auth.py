import os
import hmac
import hashlib
import binascii

ITERATIONS = 200_000

def _pbkdf2(code: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, ITERATIONS)

def hash_code(code: str) -> str:
    """
    Genere un hash sale au format 'salt_hex:hash_hex' a stocker en variable d'environnement.
    Ne necessite aucune compilation native (contrairement a bcrypt) - fonctionne partout,
    y compris sous Termux.
    """
    salt = os.urandom(16)
    digest = _pbkdf2(code, salt)
    return f"{binascii.hexlify(salt).decode()}:{binascii.hexlify(digest).decode()}"

def _check(code: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":")
        salt = binascii.unhexlify(salt_hex)
        expected = binascii.unhexlify(digest_hex)
    except (ValueError, binascii.Error):
        return False
    computed = _pbkdf2(code, salt)
    return hmac.compare_digest(computed, expected)

def _get_stored(env_name):
    val = os.environ.get(env_name, "")
    return val if val else None


def verify_code(submitted_code: str):
    """
    Compare le code recu a chaque hash stocke en variable d'environnement.
    Retourne "CID", "SAD", ou None si aucun ne correspond.
    Ne fait confiance a rien venant du client : toute la verification est ici.
    """
    if not submitted_code:
        return None

    submitted = submitted_code.strip()

    cid_stored = _get_stored("CID_CODE_HASH")
    if cid_stored and _check(submitted, cid_stored):
        return "CID"

    sad_stored = _get_stored("SAD_CODE_HASH")
    if sad_stored and _check(submitted, sad_stored):
        return "SAD"

    return None
