# Assistant vocal de prise de rendez-vous en imagerie médicale

Projet 3 du Mini Projet Data Science (Polytech INTL, ING 3) : agent conversationnel
**audio → audio** pour un centre d'imagerie. Il identifie l'examen parmi ~180, gère les
rendez-vous, répond aux questions pratiques et transfère vers un humain dès que nécessaire.
Le système n'évalue **jamais** un contenu médical.

Le code est organisé comme un **moteur d'agent générique** (`src/agentkit/`) piloté par des
**packs de domaine** (`domains/`). Détails, contrat des packs et correspondance avec le
cahier des charges : [docs/architecture.md](docs/architecture.md).

## Structure

```
src/agentkit/          moteur générique (aucun vocabulaire métier, vérifié par les tests)
  domain/              contrat des packs (pydantic) et chargement
  orchestrator.py      un tour de conversation
  agent/               contrat JSON du LLM, politiques (au plus 1 appel LLM par tour)
  llm/                 passerelle LLM (compatible OpenAI), cache, compteurs, FakeLLM
  nlu/                 routeur, résolveur de catalogue (gazetteer + RapidFuzz), clarification
  knowledge/ signals/ policy/ workflows/ tools/ logging/
  channels/audio/      qualité, STT (Whisper, Vosk, ElevenLabs), TTS (ElevenLabs, gTTS, Piper)
  channels/text/       conversation au clavier
  evaluation/          eval_stt, eval_router, eval_knowledge, eval_conversations
  server/              plateforme web : API FastAPI (comptes, agents, Playground, suivi)
web/                   application React + TypeScript (site public + application)
domains/
  imagerie_medicale/   le pack du projet : domain.yaml, data/, workflows/, prompts/,
                       builders/ (scripts de données), tests/ (données S1, gel du test)
  demo_minimal/        mini pack (location de vélos) qui prouve le découplage
tests/                 tests du moteur
docs/                  architecture.md
```

## Installation (Windows)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt          # moteur + audio + modèles + démo + tests
pip install -e .[piper]                  # facultatif : TTS hors ligne Piper
copy .env.example .env                   # puis remplir les clés
```

Clés (`.env`, jamais versionné) :
- **ElevenLabs** (synthèse vocale) : `ELEVENLABS_API_KEY`, éventuellement `ELEVENLABS_VOICE_ID`.
- **LLM** (facultatif) : toute API compatible OpenAI, ex. Gemini gratuit :
  `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`, `LLM_API_KEY`,
  `LLM_MODEL`. Sans LLM, l'agent fonctionne avec les règles seules.

## Plateforme web

Site public (présentation, solutions, démo) et application connectée : tableau de bord,
configuration des agents, Playground texte / voix, conversations, actions, analytics, base de
connaissances, réglages. Elle s'appuie sur le moteur existant (aucune intégration dupliquée).

```
pip install -r requirements.txt          # inclut l'extra [web] (FastAPI, uvicorn)
cd web && npm install && npm run build   # Node 20+ ; produit web/dist
cd .. && python -m agentkit.server -v    # http://127.0.0.1:8000  (API : /api/docs)
```

- Développement de l'interface : `python -m agentkit.server` dans un terminal, `cd web && npm run dev`
  dans un autre (http://localhost:5173, l'API est relayée).
- Importer les conversations des essais en ligne de commande (journaux déjà anonymisés) dans
  un espace de travail : `python -m agentkit.server import-logs --email vous@exemple.com`.
- Données de la plateforme : `runtime/platform/` (base SQLite, FAQ et agenda propres à chaque agent,
  audios des réponses). Les clés restent dans `.env`, côté serveur.

## Commandes

| Action | Commande |
|---|---|
| Tous les tests (sans réseau, sans crédits) | `python -m pytest` |
| Conversation texte (`-v` : étapes STT / LLM / TTS, sans texte ni clé) | `python -m agentkit.channels.text --domaine imagerie_medicale -v` |
| Appel simulé au micro (audio → audio) | `python -m agentkit.channels.audio --micro 6 --jouer -v` |
| Scénarios de bout en bout, LLM réel (texte) | `python -m agentkit.evaluation.eval_conversations --mode texte` |
| Mêmes scénarios en voix (gTTS → Whisper → LLM → ElevenLabs, ≈ 2 500 caractères) | `python -m agentkit.evaluation.eval_conversations --mode voix` |
| Synthèse d'une phrase (cache : la 2e fois ne coûte rien) | `python -m agentkit.channels.audio.tts --texte "Bonjour" --out sortie.wav --jouer` |
| Même chose avec gTTS (gratuit) | `python -m agentkit.channels.audio.tts --moteur gtts --out sortie.wav` |
| Essai de transcription (micro 6 s) | `python -m agentkit.channels.audio.essai_stt --micro 6` |
| Évaluation STT (WER) | `python -m agentkit.evaluation.eval_stt --moteurs whisper-small vosk` |
| Routage du 1er tour (WP3, sans LLM) | `python -m agentkit.evaluation.eval_router --split test` |
| FAQ : tfidf / embeddings / hybride (WP3) | `python -m agentkit.evaluation.eval_knowledge` |

Données du pack (mêmes options qu'avant, chemins par défaut dans le pack) :

| Étape | Commande |
|---|---|
| Catalogue depuis la CCAM | `python domains/imagerie_medicale/builders/build_catalogue.py --ccam <fichier>` |
| Paires confondables | `python domains/imagerie_medicale/builders/build_confusions.py` |
| Phrases annotées (graine fixe) | `python domains/imagerie_medicale/builders/build_phrases.py` |
| Audios de test (gTTS) | `python domains/imagerie_medicale/builders/build_audio.py synth` |
| Variantes bruitées (MUSAN) | `python domains/imagerie_medicale/builders/build_noise.py` |

Le jeu de test (`split=test` de `phrases_annotees.csv`) est **gelé** par le tag
`v0-test-gele` ; ne pas le modifier. Un jeu « aveugle » reste à écrire
(`domains/imagerie_medicale/data/phrases_aveugles/LISEZMOI.md`).

## État

Phase 4 (plateforme) : site public + application web multi-entreprises (espaces de travail
isolés côté serveur, agents = modèle + réglages + FAQ et agenda propres), Playground texte et
voix branché sur le moteur réel, actions et indicateurs calculés sur les conversations
enregistrées (anonymisées). Voir `docs/architecture.md` § 12.

Phase 3 : mode `llm_first` (le LLM comprend chaque tour et répond à partir de la FAQ, sources
vérifiées), dates en ISO, vérification de l'agenda avant le récapitulatif, modèles LLM de
secours, journal des étapes (`-v`), scénarios de bout en bout (`results/<pack>/conversations_*.md`).

Phase 2 (WP3) : routage évalué sur le test gelé (99,0 %, 8/8 hors périmètre transférés), FAQ
hybride avec zone grise confiée à l'appel LLM du tour (0 réponse fausse sur le jeu de mise au point).

Fait : contrat des packs, moteur générique, résolveur, routeur, FAQ, garde-fous, scripts de
sécurité, agent à un appel par tour (FakeLLM), agenda simulé, journaux anonymisés, canal
audio → audio, TTS ElevenLabs avec cache. À venir : évaluations (phases 2-3), modèle de
frustration entraîné (phase 4), dates et créneaux (phase 5), démo Gradio (phase 6).
