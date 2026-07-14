import getpass
import re
from auth import hash_code

def update_env(key, value):
    with open(".env", "r") as f:
        content = f.read()
    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}"
    with open(".env", "w") as f:
        f.write(content)

def ask(label, env_key):
    code = getpass.getpass(f"Code d'acces pour {label} : ").strip()
    if not code:
        print(f"-> Code vide pour {label}, ignore.")
        return
    hashed = hash_code(code)
    update_env(env_key, hashed)
    print(f"-> {env_key} ecrit directement dans .env")

if __name__ == "__main__":
    print("=== Generation des hash d'acces ERROR 404 AI ===\n")
    ask("CID", "CID_CODE_HASH")
    ask("SAD", "SAD_CODE_HASH")
    print("\nTermine. Verifie avec: cat .env")
