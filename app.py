import os
import base64
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, session, render_template
from dotenv import load_dotenv
import requests
from werkzeug.utils import secure_filename

from auth import verify_code

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Modeles Groq (verifie sur console.groq.com/docs/models si un modele est deprecie)
TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_TEXT_CHARS = 4000
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".json", ".csv", ".log", ".html", ".css"}

SYSTEM_PROMPT_BASE = (
    "Tu es ERROR 404 AI, cree par CID et SAD. Slogan : Think Faster. Build Smarter. "
    "Tu aides pour le developpement logiciel, la correction de code, la creation de fichiers "
    "et l'explication de concepts techniques. Reponds en francais, de maniere directe et precise. "
    "Si tu ne sais pas quelque chose avec certitude, dis-le clairement plutot que d'inventer."
)


def build_system_prompt():
    user = session.get("user")
    if user in ("CID", "SAD"):
        return (
            SYSTEM_PROMPT_BASE
            + f" L'utilisateur actuel est {user}, l'un de tes createurs, identifie via son code d'acces. "
            "Tu peux lui donner des reponses plus techniques et detaillees sur le developpement d'ERROR 404 AI lui-meme."
        )
    return SYSTEM_PROMPT_BASE


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


def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(MAX_FILE_TEXT_CHARS + 1)
        if len(content) > MAX_FILE_TEXT_CHARS:
            content = content[:MAX_FILE_TEXT_CHARS] + "\n...(tronque)"
        return content
    except Exception:
        return None


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not GROQ_API_KEY:
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

    user_text = message + file_context

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
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Erreur API Groq : {str(e)}"}), 502
    except (KeyError, IndexError):
        return jsonify({"error": "Reponse inattendue de l'API Groq."}), 502

    return jsonify({
        "reply": reply,
        "model": model,
        "user": session.get("user"),
        "timestamp": datetime.utcnow().isoformat(),
    })


if __name__ == "__main__":
    # host 0.0.0.0 pour etre accessible depuis le reseau local (utile sous Termux)
    # et pour fonctionner sur des plateformes d'hebergement comme Render/Railway
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
