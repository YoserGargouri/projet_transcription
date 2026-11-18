
# Assistant vocal de prise de rendez-vous en radiologie

## Description
Projet de développement d'un assistant vocal permettant de comprendre
les demandes des patients et d'identifier les examens radiologiques.

## Objectifs
- Reconnaissance vocale avec Faster-Whisper et Vosk.
- Identification des examens radiologiques.
- Détection des demandes ambiguës.
- Gestion des demandes de rendez-vous.
- Évaluation des performances du système.

## Structure
- data/ : catalogue, phrases annotées et données de test.
- eval/ : évaluations et annotations.
- src/ : code source.
- models/ : modèles de reconnaissance vocale.
- notebooks/ : expérimentations.

## Installation
Créer un environnement virtuel :

python -m venv venv

Activer sous Windows :

venv\Scripts\activate

Installer les dépendances :

pip install -r requirements.txt
