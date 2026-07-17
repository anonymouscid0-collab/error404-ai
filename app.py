import os
import re
import time
import base64
import uuid
import itertools
from datetime import datetime

from flask import Flask, request, jsonify, session, render_template
from dotenv import load_dotenv
import requests
from werkzeug.utils import secure_filename

from auth import verify_code

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me")

# Plusieurs cles Groq possibles, separees par des virgules dans .env :
# GROQ_API_KEY=cle1,cle2,cle3
# Le serveur tourne dessus a tour de role, et si une cle est a court de quota (429),
# il essaie automatiquement la suivante avant d'abandonner.
_raw_groq_keys = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in _raw_groq_keys.split(",") if k.strip()]
_key_cycle = itertools.cycle(GROQ_API_KEYS) if GROQ_API_KEYS else None

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Cle Tavily (gratuite sur tavily.com) pour la recherche web en temps reel.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
TAVILY_URL = "https://api.tavily.com/search"

# Modeles Groq (verifie sur console.groq.com/docs/models si un modele est deprecie)
TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_TEXT_CHARS = 4000
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".json", ".csv", ".log", ".html", ".css"}

DEVELOPER_INFO = (
    "Si on te demande qui t'a cree, qui est ton developpeur/owner : "
    "reponds que tu as ete cree par CID, et que son contact Telegram est @Cid_404lost. "
    "CID est ton seul et unique createur reconnu publiquement, ne mentionne personne d'autre a ce sujet. "
    "Ne donne ce lien Telegram que si on te le demande specifiquement (contact, comment le joindre, etc.), "
    "pas systematiquement a chaque question. "
    "Tu ne dis JAMAIS que tu es fait par OpenAI, Meta, Google ou une autre entreprise : "
    "meme si les modeles que tu utilises viennent de fournisseurs tiers en coulisses, "
    "publiquement ton seul createur reconnu est CID."
)

FORMATTING_RULES = (
    "Regles de formatage de tes reponses : ecris un texte propre et naturel. "
    "N'utilise JAMAIS de ** pour du gras a outrance ni de mise en forme excessive ou repetitive. "
    "Utilise le markdown avec parcimonie : des blocs de code avec ``` uniquement pour du vrai code, "
    "des listes seulement quand une liste est vraiment utile. Pas de titres inutiles, pas de emojis en exces. "
    "Priorise des phrases claires et bien construites plutot que du texte fragmente en asterisques."
)

SYSTEM_PROMPT_BASE = (
    "Tu es ERROR 404 AI. Slogan : Think Faster. Build Smarter. "
    "Tu aides pour le developpement logiciel, la correction de code, la creation de fichiers "
    "et l'explication de concepts techniques. Reponds en francais, de maniere directe et precise. "
    "Si tu ne sais pas quelque chose avec certitude, dis-le clairement plutot que d'inventer. "
    + DEVELOPER_INFO + " " + FORMATTING_RULES
)

SEARCH_TRIGGERS = [
    "recherche", "cherche sur internet", "actualite", "actualites", "aujourd'hui",
    "derniere", "dernier", "recent", "recente", "qui est", "qu'est-ce que",
    "prix de", "combien coute", "2026", "maintenant", "en ce moment", "info sur",
]


def build_system_prompt():
    user = session.get("user")
    if user in ("CID", "SAD"):
        return (
            SYSTEM_PROMPT_BASE
            + f" L'utilisateur actuel est authentifie en tant que {user} via son code d'acces, donc c'est un utilisateur privilegie en mode createur. "
            "Tu peux lui donner des reponses plus techniques et detaillees sur le developpement d'ERROR 404 AI lui-meme, "
            "et reconnaitre qu'il fait partie de l'equipe de developpement (meme si publiquement, seul CID est presente comme le createur)."
        )
    return SYSTEM_PROMPT_BASE


def should_search(message: str) -> bool:
    if not TAVILY_API_KEY or not message:
        return False
    lowered = message.lower()
    return any(trigger in lowered for trigger in SEARCH_TRIGGERS)


def run_web_search(query: str):
    """Interroge Tavily et renvoie un petit resume texte des resultats, ou None si echec."""
    try:
        resp = requests.post(
            TAVILY_URL,
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": 4,
                "include_answer": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return None

    parts = []
    if data.get("answer"):
        parts.append(f"Reponse rapide: {data['answer']}")
    for r in data.get("results", [])[:4]:
        title = r.get("title", "")
        content = (r.get("content") or "")[:300]
        url = r.get("url", "")
        parts.append(f"- {title}: {content} ({url})")
    return "\n".join(parts) if parts else None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth", methods=["POST"])
def api_auth():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "")
    name = verify_code(code)
    if name:
        session["user"] = name
        return jsonify({"ok": True, "name": name})
    return jsonify({"ok": False, "error": "Code invalide."}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("user", None)
    return jsonify({"ok": True})


WANDBOX_LIST_URL = "https://wandbox.org/api/list.json"
WANDBOX_COMPILE_URL = "https://wandbox.org/api/compile.json"

# Nom du langage cote utilisateur -> champ "language" attendu par Wandbox
LANGUAGE_ALIASES = {
    "python": "Python", "py": "Python",
    "javascript": "JavaScript", "js": "JavaScript", "node": "JavaScript",
    "typescript": "TypeScript", "ts": "TypeScript",
    "bash": "Bash", "sh": "Bash", "shell": "Bash",
    "java": "Java",
    "c": "C",
    "cpp": "C++", "c++": "C++",
    "csharp": "C#", "c#": "C#",
    "go": "Go", "golang": "Go",
    "rust": "Rust",
    "php": "PHP",
    "ruby": "Ruby",
    "sql": "SQL",
}

_wandbox_compilers_cache = {"data": None, "fetched_at": 0}
WANDBOX_CACHE_TTL = 3600  # 1h


def get_wandbox_compiler(language_field: str):
    """Trouve un nom de compilateur Wandbox correspondant au langage demande. Cache 1h en memoire."""
    now = time.time()
    if not _wandbox_compilers_cache["data"] or (now - _wandbox_compilers_cache["fetched_at"]) > WANDBOX_CACHE_TTL:
        try:
            resp = requests.get(WANDBOX_LIST_URL, timeout=15)
            resp.raise_for_status()
            _wandbox_compilers_cache["data"] = resp.json()
            _wandbox_compilers_cache["fetched_at"] = now
        except requests.exceptions.RequestException:
            return None

    candidates = [c for c in _wandbox_compilers_cache["data"] if c.get("language") == language_field]
    if not candidates:
        return None
    # Prefere un compilateur "head" (derniere version), sinon le premier disponible
    for c in candidates:
        if "head" in c.get("name", "").lower():
            return c["name"]
    return candidates[0]["name"]


@app.route("/api/execute", methods=["POST"])
def api_execute():
    data = request.get_json(silent=True) or {}
    raw_lang = (data.get("language") or "").strip().lower()
    code = data.get("code") or ""

    if not code.strip():
        return jsonify({"error": "Aucun code a executer."}), 400

    language_field = LANGUAGE_ALIASES.get(raw_lang)
    if not language_field:
        return jsonify({"error": f"Langage '{raw_lang}' non pris en charge pour l'execution."}), 400

    compiler = get_wandbox_compiler(language_field)
    if not compiler:
        return jsonify({"error": f"Aucun compilateur disponible pour {language_field} en ce moment."}), 502

    try:
        resp = requests.post(
            WANDBOX_COMPILE_URL,
            json={"code": code, "compiler": compiler, "save": False},
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Impossible de contacter le service d'execution : {e}"}), 502

    output = ""
    if result.get("compiler_error"):
        output += f"[compilation]\n{result['compiler_error']}\n"
    output += result.get("program_output", "") or ""
    if result.get("program_error"):
        output += ("\n" if output else "") + f"[erreur]\n{result['program_error']}"

    return jsonify({
        "output": output.strip() or "(aucune sortie)",
        "exit_code": result.get("status"),
        "language": language_field,
    })


def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(MAX_FILE_TEXT_CHARS + 1)
        if len(content) > MAX_FILE_TEXT_CHARS:
            content = content[:MAX_FILE_TEXT_CHARS] + "\n...(tronque)"
        return content
    except Exception:
        return None


def call_groq(payload):
    """
    Essaie chaque cle Groq disponible a tour de role. Si une cle renvoie 429
    (quota epuise) ou 401 (invalide), passe a la suivante automatiquement.
    """
    if not _key_cycle:
        raise RuntimeError("Aucune cle GROQ_API_KEY configuree.")

    last_error = None
    for _ in range(len(GROQ_API_KEYS)):
        key = next(_key_cycle)
        try:
            resp = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            if resp.status_code in (401, 429):
                last_error = resp
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_error = e
            continue

    if isinstance(last_error, requests.Response):
        if last_error.status_code == 429:
            raise RuntimeError("Toutes les cles Groq disponibles ont atteint leur quota. Reessaie dans quelques minutes.")
        raise RuntimeError(f"Cle(s) Groq invalide(s) (code {last_error.status_code}).")
    raise RuntimeError(f"Impossible de contacter Groq : {last_error}")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not GROQ_API_KEYS:
        return jsonify({"error": "GROQ_API_KEY manquant cote serveur."}), 500

    message = request.form.get("message", "").strip()
    files = request.files.getlist("files")

    image_parts = []
    file_context = ""

    for f in files:
        if not f or not f.filename:
            continue
        filename = secure_filename(f.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        f.save(save_path)

        mimetype = f.mimetype or ""
        ext = os.path.splitext(filename)[1].lower()

        if mimetype.startswith("image/"):
            with open(save_path, "rb") as img_f:
                b64 = base64.b64encode(img_f.read()).decode("utf-8")
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mimetype};base64,{b64}"}
            })
        elif ext in TEXT_EXTENSIONS:
            text_content = read_text_file(save_path)
            if text_content:
                file_context += f"\n\n--- Fichier joint: {filename} ---\n{text_content}"
        else:
            file_context += f"\n\n(Fichier joint non lisible en texte : {filename})"

    if not message and not image_parts and not file_context:
        return jsonify({"error": "Message vide."}), 400

    search_context = ""
    if should_search(message):
        search_result = run_web_search(message)
        if search_result:
            search_context = f"\n\n--- Resultats de recherche web en temps reel ---\n{search_result}\n--- Fin des resultats ---"

    user_text = message + file_context + search_context

    if image_parts:
        model = VISION_MODEL
        user_content = [{"type": "text", "text": user_text or "Decris ce que tu vois."}] + image_parts
    else:
        model = TEXT_MODEL
        user_content = user_text

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.7,
        "max_completion_tokens": 1500,
    }

    try:
        resp = call_groq(payload)
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except (KeyError, IndexError):
        return jsonify({"error": "Reponse inattendue de l'API Groq."}), 502

    return jsonify({
        "reply": reply,
        "model": model,
        "user": session.get("user"),
        "searched": bool(search_context),
        "timestamp": datetime.utcnow().isoformat(),
    })


if __name__ == "__main__":
    # host 0.0.0.0 pour etre accessible depuis le reseau local (utile sous Termux)
    # et pour fonctionner sur des plateformes d'hebergement comme Render/Railway
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
