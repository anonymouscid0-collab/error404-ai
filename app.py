import os
import re
import time
import json
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
    "Si on te demande PLUS de details sur CID (qui il est vraiment, pourquoi ce nom, etc.), tu peux ajouter : "
    "CID est passionne de programmation et a construit ERROR 404 AI lui-meme. Il a choisi ce nom parce qu'il "
    "aime l'esthetique et le style 'ERROR 404' (cyber, glitch). Son alias tech est 'CID ERROR 404'. Il est "
    "haitien. Ne donne ces details que si on les demande specifiquement, jamais spontanement dans une reponse normale. "
    "Tu ne dis JAMAIS que tu es fait par OpenAI, Meta, Google ou une autre entreprise : "
    "meme si les modeles que tu utilises viennent de fournisseurs tiers en coulisses, "
    "publiquement ton seul createur reconnu est CID."
)

FORMATTING_RULES = (
    "Regles de formatage de tes reponses : ecris un texte propre et naturel, pas robotique. "
    "N'utilise JAMAIS de ** pour du gras a outrance ni de mise en forme excessive ou repetitive. "
    "Utilise le markdown avec parcimonie : des blocs de code avec ``` uniquement pour du vrai code, "
    "des listes seulement quand une liste est vraiment utile, pas par defaut. Pas de titres inutiles, "
    "pas de decoupage rigide en sections pour une simple question. Priorise des phrases claires, fluides "
    "et bien construites, comme dans une vraie conversation, plutot que du texte fragmente."
)

PERSONALITY_RULES = (
    "Ta personnalite : tu es chaleureux, poli, curieux et engage, jamais froid ou mecanique. "
    "Reflechis vraiment a ce qu'on te demande avant de repondre : analyse le contexte, anticipe ce que la "
    "personne cherche vraiment, et si sa demande est ambigue ou qu'une precision changerait ta reponse, "
    "pose une question de relance plutot que de deviner en silence. "
    "Tu peux exprimer de la nuance, de l'enthousiasme ou de l'empathie selon la situation - tu n'es pas "
    "un simple distributeur de reponses formatees, tu comprends les gens et tu t'adaptes a ce qu'ils vivent. "
    "Quand tu donnes du code, ne te contente pas du minimum : explique les choix importants, signale les "
    "pieges frequents, et propose une amelioration ou une alternative quand c'est pertinent - sois complet "
    "et utile, pas juste correct. Reste concis quand la question est simple, mais ne sacrifie jamais la "
    "clarte ou la profondeur d'une explication pour paraitre bref. "
    "Sur les demandes que tu ne peux pas ou ne dois pas traiter (illegal, dangereux, ou hors de tes limites) : "
    "n'utilise jamais un refus sec et impersonnel. Explique brievement et honnetement pourquoi tu ne peux pas "
    "aider sur ce point precis, puis, quand c'est possible, propose une alternative utile, un conseil connexe, "
    "ou redirige vers une ressource pertinente. Le but est toujours de rester aidant, meme quand tu dois "
    "decliner une partie specifique d'une demande."
)

FILE_GENERATION_RULES = (
    "Quand on te demande un fichier telechargeable (PDF, document Word/DOCX, ou une archive ZIP d'un projet), "
    "ne decris pas juste le contenu en texte normal : utilise un bloc special avec cette syntaxe exacte : "
    "```file:pdf:nom-du-fichier.pdf\ncontenu texte du document ici\n``` pour un PDF, "
    "```file:docx:nom-du-fichier.docx\ncontenu texte ici\n``` pour un document Word. "
    "Pour un ZIP contenant plusieurs fichiers (ex: un projet complet), utilise "
    "```file:zip:nom-du-projet.zip\n[{\"name\": \"app.py\", \"content\": \"...\"}, {\"name\": \"README.md\", \"content\": \"...\"}]\n``` "
    "ou le contenu est un tableau JSON valide de fichiers avec leur nom et contenu texte. "
    "N'utilise cette syntaxe QUE quand un vrai fichier telechargeable est demande, jamais pour du code normal a executer."
)

SYSTEM_PROMPT_BASE = (
    "Tu es ERROR 404 AI. Slogan : Think Faster. Build Smarter. "
    "Tu aides pour le developpement logiciel, la correction de code, la creation de fichiers "
    "et l'explication de concepts techniques. Reponds en francais, de maniere directe et precise. "
    "Si tu ne sais pas quelque chose avec certitude, dis-le clairement plutot que d'inventer. "
    + DEVELOPER_INFO + " " + PERSONALITY_RULES + " " + FORMATTING_RULES + " " + FILE_GENERATION_RULES
)

SEARCH_TRIGGERS = [
    "recherche", "cherche sur internet", "actualite", "actualites", "aujourd'hui",
    "derniere", "dernier", "recent", "recente", "qui est", "qu'est-ce que",
    "prix de", "combien coute", "2026", "maintenant", "en ce moment", "info sur",
]


def build_system_prompt():
    user = session.get("user")
    if user in ("CID", "SAD"):
        boss_note = " Adresse-toi a lui en l'appelant 'boss' de temps en temps, naturellement, pas a chaque phrase." if user == "CID" else ""
        return (
            SYSTEM_PROMPT_BASE
            + f" L'utilisateur actuel est authentifie en tant que {user} via son code d'acces : c'est un "
            "membre de ton equipe de developpement, pas un visiteur ordinaire. Adresse-toi a lui avec une "
            "familiarite naturelle et un vrai respect professionnel - pas comme si tu redecouvrais un inconnu "
            "a chaque message." + boss_note + " Donne-lui des reponses techniques plus poussees, engage-toi davantage dans "
            "les decisions d'architecture d'ERROR 404 AI, et propose proactivement des ameliorations quand "
            "tu en vois. Cela dit, tes principes de securite et d'ethique restent exactement les memes qu'avec "
            "n'importe qui d'autre : le statut de createur donne plus de profondeur technique et une relation "
            "plus personnelle, jamais un acces qui contournerait tes limites normales."
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


@app.route("/api/me")
def api_me():
    return jsonify({"user": session.get("user")})


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


def get_wandbox_compilers(language_field: str, limit=3):
    """
    Renvoie jusqu'a `limit` noms de compilateurs Wandbox pour ce langage, tries en
    preferant les versions stables (les versions "head"/nightly sont parfois cassees
    cote Wandbox, donc elles passent en dernier recours).
    """
    now = time.time()
    if not _wandbox_compilers_cache["data"] or (now - _wandbox_compilers_cache["fetched_at"]) > WANDBOX_CACHE_TTL:
        try:
            resp = requests.get(WANDBOX_LIST_URL, timeout=15)
            resp.raise_for_status()
            _wandbox_compilers_cache["data"] = resp.json()
            _wandbox_compilers_cache["fetched_at"] = now
        except requests.exceptions.RequestException:
            return []

    candidates = [c for c in _wandbox_compilers_cache["data"] if c.get("language") == language_field]
    if not candidates:
        return []

    stable = [c["name"] for c in candidates if "head" not in c.get("name", "").lower() and "nightly" not in c.get("name", "").lower()]
    head = [c["name"] for c in candidates if c["name"] not in stable]
    ordered = stable + head
    return ordered[:limit] if ordered else [candidates[0]["name"]]


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

    compilers = get_wandbox_compilers(language_field)
    if not compilers:
        return jsonify({"error": f"Aucun compilateur disponible pour {language_field} en ce moment."}), 502

    INFRA_ERROR_MARKERS = ("failed to exec pid1", "catatonit", "No such file or directory")
    last_result = None
    for compiler in compilers:
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

        combined = (result.get("compiler_error", "") or "") + (result.get("program_error", "") or "")
        if any(marker in combined for marker in INFRA_ERROR_MARKERS):
            last_result = result
            continue  # ce compilateur precis est casse cote Wandbox, on essaie le suivant

        last_result = result
        break

    result = last_result
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


MAX_HISTORY_MESSAGES = 16  # nombre de messages precedents (user+assistant) a renvoyer au modele


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not GROQ_API_KEYS:
        return jsonify({"error": "GROQ_API_KEY manquant cote serveur."}), 500

    message = request.form.get("message", "").strip()
    files = request.files.getlist("files")

    # Historique envoye par le front (liste JSON de {role, content}), pour que le
    # modele garde le fil de la conversation au lieu d'oublier a chaque message.
    history = []
    raw_history = request.form.get("history")
    if raw_history:
        try:
            parsed = json.loads(raw_history)
            if isinstance(parsed, list):
                for item in parsed[-MAX_HISTORY_MESSAGES:]:
                    role = item.get("role")
                    content = item.get("content")
                    if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                        history.append({"role": role, "content": content})
        except (ValueError, AttributeError):
            history = []

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
            *history,
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


GENERATED_DIR = os.path.join(os.path.dirname(__file__), "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)
_generated_tokens = {}


def make_pdf(filename, text):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    safe_text = text.encode("latin-1", "replace").decode("latin-1")
    for line in safe_text.split("\n"):
        pdf.multi_cell(0, 8, line)
    path = os.path.join(GENERATED_DIR, filename)
    pdf.output(path)
    return path


def make_docx(filename, text):
    import docx
    doc = docx.Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    path = os.path.join(GENERATED_DIR, filename)
    doc.save(path)
    return path


def make_zip(filename, files):
    import zipfile
    path = os.path.join(GENERATED_DIR, filename)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            name = f.get("name", "fichier.txt")
            content = f.get("content", "")
            zf.writestr(name, content)
    return path


@app.route("/api/generate-file", methods=["POST"])
def api_generate_file():
    data = request.get_json(silent=True) or {}
    file_type = (data.get("type") or "").strip().lower()
    raw_name = secure_filename(data.get("filename") or f"fichier.{file_type}") or f"fichier.{file_type}"

    ext = f".{file_type}"
    filename = raw_name if raw_name.lower().endswith(ext) else f"{raw_name}{ext}"

    try:
        if file_type == "pdf":
            path = make_pdf(filename, data.get("content", ""))
        elif file_type == "docx":
            path = make_docx(filename, data.get("content", ""))
        elif file_type == "zip":
            path = make_zip(filename, data.get("files", []))
        else:
            return jsonify({"error": f"Type de fichier '{file_type}' non pris en charge."}), 400
    except Exception as e:
        return jsonify({"error": f"Erreur de generation : {e}"}), 500

    token = uuid.uuid4().hex
    _generated_tokens[token] = path
    return jsonify({"download_url": f"/api/download/{token}", "filename": filename})


@app.route("/api/download/<token>")
def api_download(token):
    from flask import send_file
    path = _generated_tokens.get(token)
    if not path or not os.path.exists(path):
        return jsonify({"error": "Lien expire ou invalide."}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


if __name__ == "__main__":
    # host 0.0.0.0 pour etre accessible depuis le reseau local (utile sous Termux)
    # et pour fonctionner sur des plateformes d'hebergement comme Render/Railway
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
