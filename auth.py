import os
import hmac
import hashlib
import binascii

ITERATIONS = 200_000

def _pbkdf2(code, salt):
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, ITERATIONS)

def hash_code(code):
    salt = os.urandom(16)
    digest = _pbkdf2(code, salt)
    return f"{binascii.hexlify(salt).decode()}:{binascii.hexlify(digest).decode()}"

def _check(code, stored):
    try:
        salt_hex, digest_hex = stored.split(":")
        salt = binascii.unhexlify(salt_hex)
        expected = binascii.unhexlify(digest_hex)
    except (ValueError, binascii.Error):
        return False
    return hmac.compare_digest(_pbkdf2(code, salt), expected)

def verify_code(submitted_code):
    if not submitted_code:
        return None
    submitted = submitted_code.strip()
    cid_stored = os.environ.get("CID_CODE_HASH", "")
    if cid_stored and _check(submitted, cid_stored):
        return "CID"
    sad_stored = os.environ.get("SAD_CODE_HASH", "")
    if sad_stored and _check(submitted, sad_stored):
        return "SAD"
    return None
