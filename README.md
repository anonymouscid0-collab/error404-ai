# ERROR 404 AI — Backend Flask

Backend pour le chatbot ERROR 404 AI (CID × SAD) : chat via Groq, upload de fichiers/images, et mode createur securise par code d'acces.

## Structure

```
error404-backend/
├── app.py              # Serveur Flask (routes /, /api/auth, /api/chat)
├── auth.py             # Verification des codes d'acces (bcrypt)
├── generate_codes.py   # Script pour generer les hash des codes CID/SAD
├── requirements.txt
├── .env.example        # Modele du fichier .env (a copier et remplir)
├── templates/
│   └── index.html      # Interface (deja branchee sur l'API)
└── uploads/             # Fichiers/images recus (cree automatiquement)
```

## Installation sous Termux

```bash
pkg update && pkg upgrade -y
pkg install python git -y

cd error404-backend
pip install -r requirements.txt
```

Si pip refuse d'installer (erreur "externally-managed-environment") :

```bash
pip install -r requirements.txt --break-system-packages
```

## Configuration

1. Recupere une cle API gratuite sur https://console.groq.com/keys
2. Copie le fichier d'exemple :

```bash
cp .env.example .env
```

3. Genere les hash de tes deux codes d'acces (CID et SAD) :

```bash
python generate_codes.py
```

Le script te demande chaque code (saisie invisible) et affiche les lignes `CID_CODE_HASH=...` et `SAD_CODE_HASH=...` a coller dans `.env`.

4. Remplis `.env` :

```
GROQ_API_KEY=ta_cle_groq
FLASK_SECRET_KEY=une_chaine_aleatoire_longue
CID_CODE_HASH=... (genere a l'etape 3)
SAD_CODE_HASH=... (genere a l'etape 3)
```

Pour generer une `FLASK_SECRET_KEY` aleatoire rapidement :

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Lancer le serveur

```bash
python app.py
```

Le site est servi sur `http://0.0.0.0:5000`. Depuis le navigateur du meme telephone : `http://127.0.0.1:5000`.

## Rendre le site accessible depuis l'exterieur

Le serveur Flask en mode `debug=True` n'est pas fait pour etre expose directement sur internet. Deux options simples depuis Termux :

**Option A — Cloudflare Tunnel (recommande, gratuit, pas de compte requis pour un lien temporaire)**

```bash
pkg install cloudflared -y
cloudflared tunnel --url http://localhost:5000
```

Le terminal affiche une URL publique (`https://xxxx.trycloudflare.com`) a partager.

**Option B — ngrok**

```bash
pkg install ngrok -y   # ou installe le binaire officiel
ngrok http 5000
```

## Mettre le site en ligne publiquement (lien permanent)

Le Cloudflare Tunnel / ngrok du dessus est parfait pour tester, mais l'URL change a chaque redemarrage et ton telephone doit rester allume. Pour un vrai lien public permanent (le lien que tu partages a tout le monde), il faut heberger le projet sur un service qui fait tourner Python en continu. **Render** a un plan gratuit et tout se fait depuis Termux, sans ordinateur.

**Etape 1 — mettre le projet sur GitHub (depuis Termux)**

```bash
pkg install git -y
cd ~/error404-backend
git init
git add .
git commit -m "ERROR 404 AI - premiere version"
```

Cree un repo vide sur github.com (app ou navigateur), puis :

```bash
git remote add origin https://github.com/TON_PSEUDO/error404-ai.git
git branch -M main
git push -u origin main
```

Le fichier `.gitignore` empeche `.env` (tes cles secretes) d'etre envoye sur GitHub — normal et voulu.

**Etape 2 — creer le service sur Render**

1. Va sur render.com, cree un compte, connecte ton GitHub
2. "New" -> "Web Service" -> choisis le repo `error404-ai`
3. Render detecte Python automatiquement. Verifie :
   - Build command : `pip install -r requirements.txt`
   - Start command : `gunicorn app:app` (deja defini dans le `Procfile`)
4. Dans l'onglet "Environment", ajoute tes variables (les memes que dans `.env`) :
   - `GROQ_API_KEY`
   - `FLASK_SECRET_KEY`
   - `CID_CODE_HASH`
   - `SAD_CODE_HASH`
5. Clique "Deploy"

Apres quelques minutes, Render te donne une URL du type `https://error404-ai.onrender.com` — **c'est le lien que tu partages**. Le site tourne meme telephone eteint.

**Important sur l'acces public :** une fois le lien public, n'importe qui peut ouvrir le chat et discuter avec ERROR 404 AI normalement — c'est voulu, c'est ton produit. Le code d'acces (menu "•••") ne sert qu'a debloquer le **mode createur** pour toi et SAD ; les autres visiteurs utilisent le chat sans jamais voir ni avoir besoin de ce code.

**Limite du plan gratuit Render :** le service s'endort apres 15 minutes sans visite et met quelques secondes a se reveiller au prochain message — normal sur le plan gratuit, pas un bug.


- Les codes d'acces ne sont **jamais** stockes en clair : seul leur hash bcrypt vit dans `.env`.
- `.env` ne doit **jamais** etre partage ni pousse sur GitHub — ajoute-le a `.gitignore`.
- Pour un usage prolonge/public, remplace `app.run(debug=True)` par un vrai serveur WSGI (ex: `waitress` fonctionne bien sous Termux) et desactive `debug`.
- Les modeles Groq changent regulierement (deprecies/remplaces) : verifie `TEXT_MODEL` et `VISION_MODEL` dans `app.py` sur https://console.groq.com/docs/models si tu as une erreur "model not found".
