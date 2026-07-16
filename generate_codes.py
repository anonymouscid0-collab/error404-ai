"""
Genere les hash (salt + pbkdf2) des codes d'acces CID et SAD.
A lancer UNE FOIS en local, jamais sur un serveur public.

Usage:
    python generate_codes.py
"""
import getpass
from auth import hash_code

def ask(label):
    code = getpass.getpass(f"Code d'acces pour {label} (invisible en tapant) : ").strip()
    if not code:
        print(f"-> Code vide pour {label}, ignore.")
        return None
    return hash_code(code)

if __name__ == "__main__":
    print("=== Generation des hash d'acces ERROR 404 AI ===\n")
    cid_hash = ask("CID")
    sad_hash = ask("SAD")

    print("\nAjoute ces lignes dans ton fichier .env :\n")
    if cid_hash:
        print(f"CID_CODE_HASH={cid_hash}")
    if sad_hash:
        print(f"SAD_CODE_HASH={sad_hash}")
    print("\nLes codes en clair ne sont jamais stockes ni affiches ailleurs qu'a l'instant de la saisie.")
