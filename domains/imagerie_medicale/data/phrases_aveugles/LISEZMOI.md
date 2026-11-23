# Jeu de test « aveugle » (à écrire par un membre de l'équipe)

Pourquoi : le gazetteer (`data/gazetteer.yaml`) a été écrit par quelqu'un qui a vu les phrases
générées par `builders/build_phrases.py`. Le score du résolveur sur ces phrases est donc
optimiste. Ce jeu mesure la vraie généralisation.

## Règles

1. Le rédacteur **n'a jamais lu** `gazetteer.yaml`, `domain.yaml`, ni `build_phrases.py`.
2. Écrire **30 à 50 phrases** comme un vrai patient au téléphone : hésitations, mots du
   quotidien (« le dos », « les carotides »), fautes d'oral, demandes incomplètes.
   - environ 60 % de prises de rendez-vous avec un examen complet ;
   - environ 20 % de demandes incomplètes (côté ou type d'examen manquant) ;
   - environ 20 % d'autres branches (rendez-vous existant, info pratique, question médicale).
3. Remplir `phrases_aveugles.csv` (mêmes colonnes que `phrases_annotees.csv`) :
   `id` (B001...), `texte`, `branche`, `examen_code` (code du catalogue, vide si incomplet),
   `info_manquante` (`cote` / `modalite` / vide), `candidats` (codes séparés par `|`),
   `hors_perimetre` (0/1). L'annotation peut être faite à deux pour la vérifier.
4. Une fois écrit, **ne plus jamais le modifier** (même règle que le jeu de test gelé).

## Les 3 chiffres du rapport (top-1 de l'identification d'examen)

| Jeu | Ce qu'il mesure |
|---|---|
| Phrases générées (split test) | plafond optimiste (même auteur que le gazetteer) |
| Phrases aveugles | généralisation à des formulations inconnues |
| Transcriptions Whisper réelles | robustesse aux erreurs de transcription |

## FAQ : reformulations aveugles (`data/faq/faq_aveugle.csv`)

Même règle : le rédacteur ne lit ni `faq.csv` (questions et variantes) ni `faq_dev.csv`.
On lui donne seulement la **liste des thèmes** (horaires, accès, documents, paiement,
résultats, délais) et il écrit **20 à 30 questions** comme un vrai appelant, dont quelques-unes
hors FAQ (colonne `attendu` vide). L'annotation de la colonne `attendu` (id de fiche) se fait
ensuite, avec `faq.csv` sous les yeux.

Puis déclarer le jeu dans `domain.yaml` :

```yaml
evaluation:
  knowledge:
    - id: faq_aveugle
      file: data/faq/faq_aveugle.csv
      blind: true
```

et lancer `python -m agentkit.evaluation.eval_knowledge`. Ne plus jamais régler `min_score` /
`min_gap` ensuite : le chiffre aveugle est celui du rapport.
