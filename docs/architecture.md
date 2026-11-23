# Architecture : un moteur générique, des packs de domaine

> Projet 3 — Agent conversationnel pour centre d'appel (imagerie médicale).
> Premier cas d'usage d'un moteur d'agent réutilisable : **le moteur ne contient aucun
> savoir métier**, tout le métier vit dans un **pack de domaine**.

## 1. Principe

```
                 ┌──────────────── canaux (entrée / sortie) ────────────────┐
  audio ───────► │ channels/audio : qualité -> STT ......... TTS -> audio   │
  texte ───────► │ channels/text                                           │
                 └───────────────┬──────────────────────────▲──────────────┘
                                 │ texte                    │ réponse
                 ┌───────────────▼──────────────────────────┴──────────────┐
                 │                 orchestrator.py (un tour)                │
                 │  signals · policy/guardrails · nlu/router · knowledge    │
                 │  nlu/resolver · agent/policy (≤ 1 appel LLM) · workflows │
                 │  tools · policy/escalation · logging/redaction           │
                 └───────────────┬─────────────────────────────────────────┘
                                 │ lit (jamais l'inverse)
          ┌──────────────────────▼───────────────────────┐
          │  pack de domaine : domains/<nom>/             │
          │  domain.yaml · data/ · workflows/ · prompts/  │
          │  tools/ (rare) · builders/ · tests/           │
          └───────────────────────────────────────────────┘
```

- **`src/agentkit/`** — le moteur, une bibliothèque installable (`pip install -e .`). Aucun
  vocabulaire métier : un test (`tests/test_decouplage.py`) vérifie qu'aucun module n'importe
  un pack et que ni « IRM », « examen », « patient », « rendez-vous »… n'apparaît dans le code
  ou les commentaires (mots entiers : « confirmer » contient « irm » mais n'est pas signalé).
- **`domains/<nom>/`** — un pack : de la **configuration et des données**, pas un paquet
  Python. Il est chargé par son chemin (`DOMAINS_DIR`), pourra venir d'une base ou d'un
  envoi par API, et ne fait jamais partie de la bibliothèque livrée.
- **Test d'acceptation** : `demo_minimal` (location de vélos) tourne avec le même moteur que
  `imagerie_medicale`, sans une ligne de code moteur spécifique.

## 2. Un tour de conversation

| # | Étape | Module | LLM ? |
|---|---|---|---|
| 0 | Audio : filtrage (passe-haut, 16 kHz), mesure (durée, niveau, SNR) | `channels/audio/quality.py` | non |
| 0 | Transcription + confiance ; décision ok / confirmer / redemander | `channels/audio/stt.py` | non |
| 1 | Signaux en parallèle (frustration) | `signals/` | non |
| 2 | Demande explicite d'un humain → transfert | `policy/guardrails.py` | non |
| 3 | Réponse à une question de sécurité en attente (script fixe) | `policy/guardrails.py` | non |
| 4 | Réponse à une confirmation en attente | `orchestrator.py` | non |
| 5 | Intention (règles du pack), puis sujets interdits → transfert | `nlu/router.py`, `policy/guardrails.py` | non |
| 6 | Escalade par signal (seuil du pack) | `policy/escalation.py` | non |
| 7 | Information générale : fiche FAQ lue mot pour mot | `knowledge/retriever.py` | non |
| 8 | Workflow : résolveur (élément du catalogue), puis **politique d'agent** | `nlu/resolver.py`, `agent/policy.py` | **≤ 1** |
| 9 | Revalidation (élément ∈ candidats, slots validés), scripts de sécurité, slot suivant, confirmation, outil final | `orchestrator.py`, `workflows/`, `tools/` | non |
| 10 | Journal anonymisé ; TTS | `logging/redaction.py`, `channels/audio/tts.py` | non |

**C'est toujours le système qui choisit l'étape suivante** ; le LLM extrait des informations
et formule la réponse. Il ne déclenche ni action, ni question de sécurité, ni transfert sans
passer par les règles.

## 3. Politique d'appels LLM (D1) : « au plus un appel par tour »

Le cahier des charges demande « un seul appel LLM par tour » et « règles et recherche floue
d'abord, LLM en secours ». Nous l'interprétons comme **au plus un** appel :

- 0 appel quand les règles suffisent : FAQ trouvée, question de clarification précise,
  script de sécurité, confirmation, transfert ;
- 1 appel quand il faut comprendre du texte libre (date, nom, demande floue).

La passerelle (`llm/gateway.py`) **refuse un 2e appel dans le même tour** (`TurnCallLimit`).
La seule exception est une **nouvelle tentative** quand la sortie est invalide : elle fait
partie du même appel logique et est comptée à part (`usage.retries`). Le nombre d'appels par
tour est une propriété de la **politique d'agent** (`AgentPolicy.max_llm_calls_per_turn`) :
une future `ToolLoopPolicy` (plusieurs étapes outil/LLM) s'ajoutera sans toucher à
l'orchestrateur.

## 4. Pourquoi le secours LLM du bot niveau 1 est fusionné dans l'appel de l'agent (D2)

La spec décrit deux étages qui peuvent appeler le LLM : le **bot niveau 1** (« LLM en secours
avec candidats seulement ») et l'**agent niveau 2** (« un seul appel LLM par tour »). Appelés
l'un après l'autre, ils feraient **deux appels** dans un tour où la demande est floue :
latence et coût doublés, et règle du cahier des charges violée.

Exemple : « je voudrais une écho des carottes ide vers 10 h jeudi » (transcription fautive de
« carotides »). Le gazetteer reconnaît la modalité mais pas la région ; la confiance est basse.
- Version naïve : (1) le bot demande au LLM « lequel parmi ECH_VCO, ECH_VMI… ? », puis (2)
  l'agent demande au LLM « extrais la date et rédige la réponse ». Deux appels.
- Version retenue : le résolveur ne fait **aucun** appel ; il fournit la liste de candidats.
  L'unique appel de l'agent reçoit le texte et ces candidats et renvoie, en une fois,
  `{item_code: "ECH_VCO", slots: {creneau: "jeudi 10h"}, reply: ...}`. Le résolveur
  revalide ensuite que `ECH_VCO` fait bien partie des candidats.

Pour l'évaluation demandée (« top-1 : gazetteer seul vs gazetteer + LLM ; % d'appels au
LLM »), le résolveur garde un **point d'accroche hors ligne** (`CatalogueResolver.llm_fallback`)
qui mesure le bot **seul** sur les phrases annotées, avec le même fragment de prompt que
l'agent : la mesure reflète le fonctionnement réel, sans appel supplémentaire en conversation.

## 4 bis. Base de connaissances : trois zones (phase 2)

Une fiche n'est lue **directement** (0 appel LLM) que si elle est assez sûre
(`min_score`) **et** nettement devant la 2e (`min_gap`) : deux fiches voisines presque à
égalité (« samedi » / « dimanche », « fermeture le soir » / « ouvert le midi ») sont le cas
typique d'erreur confiante. Entre `min_score - llm_margin` et ces seuils, c'est la **zone
grise** : l'unique appel LLM du tour reçoit les `llm_top_k` meilleures fiches et renvoie
`knowledge_id` (une de ces fiches, ou `null`) ; la réponse est **la fiche, mot pour mot**,
jamais un texte rédigé par le LLM. Sans LLM, la zone grise devient « reformulez » puis un
transfert. Objectif mesuré : **zéro réponse fausse** (une absence de réponse se rattrape,
une information fausse non).

Le routage du premier tour reste sans LLM ; évalué par `eval_router` sur les jeux déclarés
dans `evaluation.intents` du pack.

## 4 ter. Mode `llm_first` : le LLM comprend chaque tour (phase 3)

Constat sur les premiers appels réels : en `rules_first`, une demande que **aucune règle ne
reconnaît** est perdue, même quand le LLM l'aurait comprise. « Je voudrais prendre un ronds des
vous » (ou « … un haut niveau », transcription de Whisper) n'active aucun motif → la FAQ ne
trouve rien → « Excusez-moi, je n'ai pas bien compris ». Le LLM n'était appelé que pour choisir
une fiche FAQ (zone grise) ou extraire des slots dans une démarche déjà commencée, et sa
réponse rédigée était ignorée hors démarche.

Avec `llm.mode: llm_first` (pack imagerie_medicale), l'étape 5 devient **un appel LLM qui
comprend le tour** — toujours **un seul** par tour (D1) :

| Le LLM reçoit | Le LLM renvoie (contrat pydantic, validé) |
|---|---|
| intentions et démarches du pack (en tête de prompt, fixe) ; historique ; date du jour ; démarche en cours, informations obtenues et manquantes ; candidats du catalogue (+ `catalogue.llm_columns`) ; **base de connaissances** (`knowledge.llm_context` : `all` ou `top_k`) ; options proposées par l'outil ; indice des règles ; alerte de périmètre (motif faible) | `intent`, `understood`, `slots` (dates en ISO), `item_code` ∈ candidats, **`sources`** ⊆ fiches/candidats fournis, `asks_for` (information demandée), `analysis` (non lue), `reply`, `sentiment`, `escalate` |

Ce qui **reste hors LLM** : demande d'humain, motifs **forts** du périmètre interdit (transfert
immédiat, l'appel LLM n'a pas lieu), scripts de sécurité (question et interprétation de la
réponse), oui/non nets à une confirmation, revalidation de l'élément (D3), validation des
slots, **vérification par l'outil** avant le récapitulatif (créneau libre, référence existante →
sinon alternatives `unavailable_message`), récapitulatif, action finale.

**Réponses ancrées dans la base** (`knowledge.answer_mode: grounded`) : le LLM rédige la
réponse à partir des fiches fournies et doit citer leurs id dans `sources`. Une source hors
liste est retirée (D3 appliqué aux fiches) ; une réponse d'information **sans source** est
remplacée par `persona.no_answer_message`. `verbatim` garde l'ancien comportement (fiche lue mot
pour mot).

**Repli** : si le LLM échoue (surcharge 503/429, délai, sortie invalide), le tour repart sur
le chemin `rules_first` (règles, résolveur, FAQ par zones, analyse de dates de secours
`nlu/dates.py`). `LLM_FALLBACK_MODELS` : modèles de secours essayés tout de suite, dans le
budget `LLM_TIMEOUT_S`.

**Transcriptions fautives** : le prompt du pack prévient le LLM que le message vient d'un STT
(« ronds des vous » = « rendez-vous ») ; `channels.audio.stt.prompt` donne aussi le vocabulaire
du métier à Whisper.

Le routeur par règles reste **évalué seul** (`eval_router`, exigence de la spec) ; il est
désormais l'indice et le repli de l'agent. Le comportement de bout en bout est mesuré par
`eval_conversations` (scénarios du pack, en texte et en voix).

## 5. Contrat de sortie de l'agent (D3)

Le modèle pydantic de la sortie est **généré à chaque tour** à partir du pack
(`agent/contract.py`) :

| Champ | Contrainte |
|---|---|
| `intent` | une des intentions du pack |
| `slots` | uniquement les slots du workflow en cours (hors élément du catalogue) |
| `item_code` | **un des candidats de ce tour**, ou `null` (élément déjà fixé : lui seul) |
| `tool_call` | outil enregistré, ou `null` (phase 1 : les actions passent par la confirmation) |
| `reply` | texte non vide |
| `sentiment` | `positif` / `neutre` / `negatif` |
| `escalate` | `{needed: bool, reason: str}` |

On ne compte pas sur le fournisseur pour respecter l'énumération : la passerelle valide avec
pydantic ; si `item_code` n'est pas un candidat, **une** nouvelle tentative avec le message
d'erreur ; si c'est encore faux, `item_code` est remis à `null` et le reste de la sortie est
gardé (question de clarification ou transfert). **Un code hors candidats n'est jamais accepté.**

## 6. Contrat d'un pack de domaine (`domain.yaml`)

Schéma : `src/agentkit/domain/schema.py` (pydantic, `extra="forbid"` : une clé inconnue est
une erreur). Schéma JSON exportable : `DomainPack.model_json_schema()`. Les motifs (`patterns`)
sont des regex sur le texte **normalisé** (minuscules, sans accents ni ponctuation). Les
chemins sont relatifs au pack. `${VAR}` / `${VAR:-défaut}` sont remplacés par l'environnement
(les secrets restent dans `.env`).

### 6.1 Identité et persona
| Champ | Rôle |
|---|---|
| `schema_version` | version du contrat (1) |
| `id` | identifiant (`[a-z0-9_]+`), égal au nom du dossier conseillé |
| `name`, `description` | présentation |
| `language` | code ISO 639-1 : langue du STT et du TTS |
| `persona.name`, `style` | injectés dans le prompt système |
| `persona.greeting`, `handoff_message`, `fallback_message`, `goodbye_message`, `not_found_message`, `change_prompt` | phrases dites telles quelles |

### 6.2 Périmètre
| Champ | Rôle |
|---|---|
| `scope.description`, `allowed` | ce que fait l'agent (prompt) |
| `scope.forbidden[]` | sujets interdits : `patterns` (toujours), `weak_patterns` (sauf si l'intention est dans `except_if_intents`), action `escalate` |
| `scope.human_request_patterns` | demande explicite d'un humain |

### 6.3 Intentions
`intents[]` : `id`, `description`, `handler` (`workflow:<id>` · `knowledge` · `escalate`),
`patterns` (routeur sans LLM), `examples`, `priority` (testées par priorité décroissante),
`default` (une seule, retenue si aucune règle ne s'applique), `group` (regroupement, ex.
branche d'évaluation `rdv_existant` pour annuler / déplacer / consulter).

### 6.4 Catalogue et résolution
| Champ | Rôle |
|---|---|
| `file`, `id_column`, `label_column` | fichier CSV des éléments |
| `attributes[]` | **ordre = ordre des filtres** (filtre A, B…). Pour chacun : `column`, `on_missing` (`ask` = demander si plusieurs valeurs restent / `default` = prendre `default`), `not_applicable` (valeurs jamais demandées), `question` (obligatoire si `ask`, avec `{options}`), `option_labels` (libellés oraux, aussi reconnus), `fuzzy`, `match_values` (reconnaître la valeur brute ; `false` pour des codes comme G/D ou oui/non) |
| `gazetteer` | YAML `attribut → valeur → formes orales` (écrit à la main) |
| `synonym_columns`, `synonym_separator` | synonymes au niveau élément (liste courte pour le LLM) |
| `fuzzy.min_score`, `min_length`, `exclude_words` | réglages RapidFuzz ; vrais mots jamais « corrigés » |
| `confusions` | paires confondables ; **le type de confusion = le nom de l'attribut qui diffère** |
| `confidence.accept`, `confirm`, `confusable_penalty`, `default_penalty` | seuils et pénalités |
| `shortlist_size` | nombre max de candidats montrés au LLM |
| `options_joiner` | mot avant la dernière option (« ou ») |

### 6.5 Connaissances, workflows, outils
| Champ | Rôle |
|---|---|
| `knowledge` | FAQ CSV : colonnes `id` / `question` / `reponse` / `variantes` ; `retriever` (`tfidf` / `embeddings` / `hybrid`), `embeddings_model`, `lexical_weight`, `min_score`, `min_gap`, `llm_margin`, `llm_top_k` ; **`answer_mode`** (`verbatim` / `grounded`) ; **`llm_context`** (`top_k` / `all`) |
| `evaluation` | jeux d'évaluation : `intents[]` (`file`, `text_column`, `label_column`, `split_column`, `out_of_scope_column`, `escalate_label`), `knowledge[]` (`file`, `text_column`, `expected_column`, `blind`), **`conversations`** (YAML de scénarios de bout en bout) |
| `workflows[]` | chemin d'un YAML ou définition inline : `id`, `description`, `slots[]` (`name`, `type`, `required`, `prompt`, `pii`, `choices`, `pattern`), `confirmation`, `on_complete` (`tool`, `action`, `arguments` avec `{slots.x}`, `{item.x}`), `success_message` (`{result.x}`) |
| `tools[]` | `name` + **`builtin`** (outil du moteur, configuré par `config`) **ou** `entrypoint` (`tools/<fichier>.py:<Classe>`, dans le pack, liste blanche) |

Outil intégré `calendar` (D4) : `resources` ou `resource_attribute` (chaque valeur d'un
attribut = une ressource), **`duration_field`** (colonne du catalogue donnant la durée),
`default_duration_min`, `slot_step_min`, `horizon_days`, `reference_prefix`, `opening_hours`
(`mon`…`sun` → plages `HH:MM-HH:MM`). Actions : `free_slots`, `book`, `find`, `cancel`, `move`.
Vérifications sans écriture (`Tool.check`, appelées avant le récapitulatif) : créneau passé,
hors horaires ou pris → 3 alternatives espacées ; référence inconnue ou déjà annulée. Les
références sont comparées sans espaces ni tirets (« R D V tiret A B 1 2 » = `RDV-AB12`).
Les slots `date` / `time` / `datetime` sont stockés en ISO et lus en toutes lettres dans les
messages (« jeudi 26 novembre à 10 heures »).

### 6.6 Signaux, escalade, sécurité, réponses
| Champ | Rôle |
|---|---|
| `signals[]` | `id`, `kind` (`lexicon` / `model`), `patterns`, `model`, `threshold` (détection) |
| `escalation` | `max_failed_clarifications`, `max_audio_failures`, `max_unrecognised_turns`, `signal_thresholds` (signal → transfert) |
| `safety_scripts[]` | `applies_if` (attribut → valeurs), `question` fixe, `on_yes: escalate`, `on_unclear` (`ask_again_once` / `escalate`) |
| `answers.positive`, `answers.negative` | reconnaissance oui / non (clés différentes de `yes`/`no`, lues comme booléens en YAML) |

### 6.7 Canaux, LLM, journaux
| Champ | Rôle |
|---|---|
| `channels.audio.stt.engine` | `whisper-small`, `vosk`, `elevenlabs`… |
| `channels.audio.stt.prompt` | vocabulaire du métier donné à Whisper (`initial_prompt`) |
| `channels.audio.tts` | `engine`, `voice_id`, `model_id`, `fallback`, `settings` |
| `channels.audio.quality` | seuils : durée, niveau, SNR, confiance STT |
| `channels.audio.retry_message` | phrase quand l'audio est inexploitable |
| `llm.system_prompt` | texte ou fichier du pack ; `{persona_name}`, `{scope}`, `{style}` remplacés |
| `llm.max_history_turns` | historique envoyé au LLM |
| `llm.mode` | `rules_first` (règles d'abord, LLM en secours) / `llm_first` (le LLM comprend chaque tour, § 4 ter) |
| `persona.no_answer_message`, `persona.unavailable_message` | pas de source dans la base ; valeur refusée par l'outil (`{options}`) |
| `catalogue.llm_columns` | colonnes montrées au LLM avec chaque candidat, citables dans `sources` |
| `logging.extra_patterns` | motifs à masquer en plus des génériques |

## 7. Ajouter un domaine, pas à pas

1. Copier `domains/demo_minimal/` en `domains/<nouveau>/`.
2. Remplacer `data/catalogue.csv` ; déclarer ses colonnes dans `catalogue.attributes`
   (dans l'ordre où l'on veut filtrer) et écrire les questions de clarification.
3. Écrire `data/gazetteer.yaml` (formes orales de chaque valeur).
4. Déclarer les intentions et leurs motifs ; une seule `default: true`.
5. Écrire les workflows (slots, confirmation, outil final) ; choisir les outils intégrés
   (`builtin: calendar`) avant d'écrire du code.
6. Remplir `scope` (sujets interdits), `safety_scripts`, `signals`, `escalation`.
7. Vérifier : `python -c "from agentkit.domain import load_domain; load_domain('<nouveau>')"`
   (toutes les erreurs sont listées), puis `python -m agentkit.channels.text --domaine <nouveau>`.
8. Ajouter `domains/<nouveau>/tests/` (données) ; `python -m pytest`.

**Aucune modification de `src/agentkit/` n'est nécessaire.** Si elle semble l'être, c'est
qu'il manque un champ au contrat : on l'ajoute au schéma (générique, documenté, testé).

## 8. Le futur générateur « prompt client → pack »

```
prompt du client ──► LLM générateur ──► domain.yaml + CSV + workflows ──► load_domain()
   (métier, tâches,      (schéma JSON de       (outils INTÉGRÉS             (validation : refus
    contraintes)          DomainPack fourni)     seulement)                   motivé, à corriger)
```

- Le générateur reçoit `DomainPack.model_json_schema()` comme contrat de sortie.
- Il **compose des outils intégrés** (`builtin`) au lieu d'écrire du Python : pas de code
  généré exécuté sur nos serveurs.
- `load_domain()` est le juge : erreurs regroupées et lisibles, renvoyées au générateur pour
  correction (boucle « génère → valide → corrige »).
- Les tests de découplage garantissent que le moteur reste générique au fil des packs.

## 9. Correspondance cahier des charges → modules

| Lot / barème | Modules | État phase 1 |
|---|---|---|
| WP1 Données simulées | `domains/imagerie_medicale/data`, `builders/` | fait (S1) ; jeu aveugle à écrire |
| WP2 STT + qualité | `channels/audio/stt.py`, `quality.py`, `evaluation/eval_stt.py` | fait ; confirmation en qualité moyenne : TODO |
| WP2 TTS | `channels/audio/tts.py` (ElevenLabs, gTTS, Piper) | fait ; grille d'écoute : TODO |
| WP3 Qualification + FAQ | `nlu/router.py`, `knowledge/retriever.py`, `evaluation/eval_router.py`, `evaluation/eval_knowledge.py` | fait (phase 2) ; FAQ aveugle à écrire |
| WP4 Bot niveau 1 (4 pts) | `nlu/resolver.py`, `disambiguation.py`, `gazetteer.yaml` | baseline ; évaluation gazetteer seul vs + LLM : phase 3 |
| WP5 Détecteur de frustration (4 pts) | `signals/` | lexique ; MLP entraîné : phase 4 |
| WP6 Agent niveau 2 (3 pts) | `agent/contract.py`, `agent/policy.py`, `workflows/`, `tools/builtin/calendar.py` | appel unique + JSON fait ; dates, créneaux : phase 5 |
| WP7 Escalade + journaux (3 pts) | `policy/escalation.py`, `policy/guardrails.py`, `logging/redaction.py` | fait ; démo Gradio : phase 6 |
| Chaîne audio → audio (3 pts) | `channels/audio/channel.py` | fait (fichier par tour) |
| Évaluation comparative (3 pts) | `evaluation/` | STT ; le reste en phases 2 à 6 |

## 10. Évaluation honnête de l'identification d'examen

Trois chiffres de top-1 seront rapportés (phase 3) :

| Jeu | Ce qu'il mesure |
|---|---|
| Phrases générées (split test, gelé) | plafond optimiste : le gazetteer a été écrit par quelqu'un qui a vu ces phrases |
| Phrases aveugles (30-50, écrites par un membre qui n'a pas vu le gazetteer) | généralisation |
| Transcriptions Whisper réelles | robustesse aux erreurs de transcription |

Le jeu de test est gelé par le tag Git `v0-test-gele` (lignes `split=test` seulement) ; un
test vérifie aussi qu'aucune phrase d'entraînement ne recopie une phrase de test ni n'utilise
un gabarit réservé au test.

## 11. Secrets, crédits, données

- Clés dans `.env` (jamais versionné) ; modèle : `.env.example`.
- ElevenLabs : cache disque par hash(moteur, texte, voix, modèle, réglages, langue), journal
  des caractères facturés (`runtime/logs/tts_usage.jsonl`) ; **les tests ne peuvent pas
  l'appeler** (client bloqué par `conftest.py`).
- LLM : cache disque, compteurs d'appels / jetons / latence, plafonds `LLM_MAX_CALLS`,
  `LLM_MAX_TOKENS`.
- Données entièrement simulées ; journaux anonymisés (slots `pii`, téléphone, e-mail, dates,
  numéro de sécurité sociale) — loi organique n° 2004-63.
