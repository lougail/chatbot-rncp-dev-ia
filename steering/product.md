# Product — chatbot-rncp-dev-ia

> Dernière mise à jour : 2026-04-30

## Vision

Un chatbot conversationnel qui aide formateurs et apprenants Simplon à vérifier en quelques secondes si un projet de formation couvre les compétences du référentiel RNCP "Développeur en intelligence artificielle" (titre 2023). L'utilisateur décrit son projet en langage naturel, l'assistant identifie les compétences validées avec citations textuelles du référentiel, et liste celles qu'il manque.

## Objectif principal

**Remplacer la relecture manuelle de 62 pages** par une analyse semi-automatique fiable, traçable (citations) et instantanée (latence sub-seconde).

## Personas

### Persona 1 — Apprenant Simplon Dev IA
- **Qui :** Apprenant en formation, à 2-4 semaines de la soutenance
- **Besoin :** Vérifier rapidement quelles compétences son projet valide pour identifier les manques
- **Frustration :** Lire 62 pages de référentiel à la dernière minute, sans certitude d'avoir bien compris

### Persona 2 — Formateur Simplon
- **Qui :** Formateur encadrant une promo Dev IA
- **Besoin :** Évaluer rapidement la couverture d'un projet pour conseiller l'apprenant
- **Frustration :** Re-lire le référentiel pour chaque projet d'apprenant, subjectivité de l'évaluation

### Persona 3 — Sofia (Responsable pédagogique)
- **Qui :** Responsable pédagogique, commanditaire du projet
- **Besoin :** Outil réutilisable par toutes les promos Dev IA, sans saisie manuelle
- **Frustration :** Inconsistance entre formateurs sur l'évaluation des projets

## Ton et voix

- **Registre :** Factuel, professionnel, pédagogique
- **Langue :** Français exclusivement
- **À éviter :** Jargon ML excessif (l'utilisateur n'est pas forcément technicien IA), adjectifs flatteurs ("excellent projet"), évaluation subjective de la qualité du projet

## Métriques de succès

| Métrique | Cible | Comment mesurer |
|----------|-------|-----------------|
| Temps d'analyse d'un projet | < 5 secondes | Latence end-to-end |
| Pertinence du retrieval (Phase 2) | Recall@5 > 0.80 | Golden set RAGAS |
| Anti-hallucination | 0 compétence inventée | Tests manuels sur 30 projets |
| Adoption | 1 promo Dev IA testée | Feedback utilisateur |

## Équipe

| Prénom | Handle Git | Rôle |
|--------|-----------|------|
| Louis | louis-gaillard | Apprenant Simplon Dev IA — concepteur et développeur |

## Non-objectifs

- **Évaluer la qualité technique du projet** — l'outil identifie une couverture, il ne note pas
- **Remplacer le jury de soutenance** — c'est un outil d'auto-évaluation, pas de validation officielle
- **Ingérer plusieurs référentiels** dans la même collection
- **Multi-utilisateurs avec auth** — usage local en démo, pas de SaaS

## Concurrence / références

| Nom | Ce qu'on aime | Ce qu'on fait différemment |
|-----|---------------|---------------------------|
| ChatGPT + copy-paste du référentiel | Universel, accessible | RAG : citations exactes, latence sub-seconde, traçabilité |
| Outils HR matching | Volumes énormes | Spécifique référentiel Simplon, FR natif, open source |

## Évolutions envisagées

- Phase 2 : hybrid search (BM25 + dense) + reranker `bge-reranker-v2-m3`
- Phase 3 : RAGAS + golden set + Langfuse pour l'observabilité
- Phase 4 : LangGraph routeur Adaptive RAG (codes C13 → tool, sémantique → RAG)
- Bonus : MCP server pour réutilisation par d'autres agents
