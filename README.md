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
  evaluation/          eval_stt
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

## Commandes

| Action | Commande |
|---|---|
| Tous les tests (sans réseau, sans crédits) | `python -m pytest` |
| Conversation texte | `python -m agentkit.channels.text --domaine imagerie_medicale --trace` |
| Synthèse d'une phrase (cache : la 2e fois ne coûte rien) | `python -m agentkit.channels.audio.tts --texte "Bonjour" --out sortie.wav --jouer` |
| Même chose avec gTTS (gratuit) | `python -m agentkit.channels.audio.tts --moteur gtts --out sortie.wav` |
| Essai de transcription (micro 6 s) | `python -m agentkit.channels.audio.essai_stt --micro 6` |
| Évaluation STT (WER) | `python -m agentkit.evaluation.eval_stt --moteurs whisper-small vosk` |

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

## État (phase 1 : architecture)

Fait : contrat des packs, moteur générique, résolveur, routeur, FAQ, garde-fous, scripts de
sécurité, agent à un appel par tour (FakeLLM), agenda simulé, journaux anonymisés, canal
audio → audio, TTS ElevenLabs avec cache. À venir : évaluations (phases 2-3), modèle de
frustration entraîné (phase 4), dates et créneaux (phase 5), démo Gradio (phase 6).
