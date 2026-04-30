# Scénarios de démonstration — Soutenance

> 3 scénarios préparés pour la démonstration live de 10 minutes.
> Tester sur http://localhost:8000 (après `docker compose up qdrant -d` + `uv run python -m src.ingest` + `uv run chainlit run app.py`).

---

## Scénario 1 — Projet riche multi-blocs (cas nominal)

**Profil** : apprenant qui a couvert plusieurs facettes du référentiel (data, modèle, application, MLOps).

**Prompt à coller** :

```
Mon projet déploie une API FastAPI avec Docker et un pipeline GitHub Actions
qui lance les tests pytest, build l'image Docker et déploie sur Cloud Run.
J'ai aussi mis en place du monitoring Prometheus avec des dashboards Grafana.
Quelles compétences RNCP couvre-t-il ?
```

**Compétences attendues (validation manuelle)** :

| Code | Libellé court | Élément du projet |
|------|---------------|-------------------|
| **C5** ✅ | Développer une API REST | FastAPI |
| **C11** ✅ | Monitorer un modèle IA | Prometheus + Grafana |
| **C13** ✅ | Chaîne livraison continue modèle | GitHub Actions sur image Docker |
| **C20** ✅ | Surveiller une application | Logs + monitoring |
| C18 ⚠️ | Tests automatisés | pytest mentionné |
| C19 ⚠️ | Livraison continue application | Cloud Run |

**Ce qu'on montre au jury** :
- Streaming token-par-token de la réponse (Chainlit)
- Affichage des sources avec page (4 ou 5 du référentiel)
- Format de sortie structuré (Validées / À approfondir / Non couvertes / Synthèse par bloc)

---

## Scénario 2 — Question ciblée sur un code de compétence

**Profil** : apprenant qui veut vérifier UNE compétence précise.

**Prompt à coller** :

```
La compétence C13 est-elle validée si j'ai seulement un Dockerfile sans CI/CD ?
```

**Réponse attendue** :
- Le chatbot doit retourner le **libellé exact** de C13 :
  > *"Créer une chaîne de livraison continue d'un modèle d'intelligence artificielle en installant les outils et en appliquant les configurations souhaitées, dans le respect du cadre imposé par le projet et dans une approche MLOps, pour automatiser les étapes de validation, de test, de packaging et de déploiement du modèle."*
- Conclusion attendue : **C13 NON validée** car un Dockerfile seul ne suffit pas — il manque la chaîne d'**intégration continue** + automatisation des étapes (validation, test, packaging, déploiement).

**Ce qu'on montre au jury** :
- Capacité du chatbot à **différencier** les exigences (Dockerfile ≠ pipeline CI/CD complet)
- Citation textuelle du référentiel (preuve d'ancrage, pas d'hallucination)
- Précision : C13 vs C19 (modèle vs application — confusion classique)

---

## Scénario 3 — Question hors-scope (test anti-hallucination)

**Profil** : utilisateur qui pose une question sans rapport.

**Prompt à coller** :

```
Quelle est la meilleure recette de cookies au chocolat ?
```

**Réponse attendue** :
- Le chatbot doit répondre :
  > *"🤔 Je n'ai trouvé aucun extrait pertinent dans le référentiel pour cette question. Reformule ou détaille davantage ton projet."*

OU si des chunks remontent quand même (peu probable mais possible) :
  > *"Information insuffisante dans les extraits fournis."*

**Ce qu'on montre au jury** :
- **Garde-fou anti-hallucination** : le LLM ne invente pas de "compétence cookie"
- Le retriever filtre les chunks au-dessus du `score_threshold`
- Le prompt système **interdit explicitement** d'inventer des compétences absentes

---

## Préparation matérielle

### Avant la soutenance (la veille)
1. `docker compose up qdrant -d`
2. `uv run python -m src.ingest --recreate` (vérifier "21 chunks indexés")
3. Tester les 3 prompts ci-dessus → screenshots de référence

### Pendant la soutenance
1. `uv run chainlit run app.py` dans un terminal visible
2. Avoir le navigateur ouvert sur http://localhost:8000
3. Avoir les 3 prompts prêts dans un fichier texte / Notion pour copier-coller (pas de typo en live)
4. Backup : si Mistral API down → diapositive avec screenshots des 3 démos faites en amont

### Plan B si la démo plante
- Montrer les screenshots préparés
- Expliquer l'architecture sur le schéma du README
- Faire un walkthrough du code (`src/chain.py` est lisible)
