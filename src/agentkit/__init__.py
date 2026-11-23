"""
agentkit : moteur d'agent conversationnel, indépendant de tout domaine métier.

Tout le savoir métier (catalogue, intentions, workflows, outils, prompts, seuils) vit dans un
« pack de domaine » (dossier domains/<nom>/ décrit par domain.yaml). Le moteur ne contient
aucun vocabulaire métier : changer de pack ne demande aucune modification du code.
Voir docs/architecture.md.
"""

__version__ = "0.1.0"
