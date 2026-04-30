# Roadmap V2 — Améliorations pour faire de l'outil un produit incroyable

> **Date** : 2026-04-30
> **Contexte** : V1 livrée pour le brief Simplon. Ces idées sont pour V2+.
> **Idée déclencheuse** (Louis) : *"Donner un repo GitHub au chatbot et qu'il analyse le projet par rapport au référentiel"*.

---

## 🌟 Idée 1 — Analyse automatique d'un repo GitHub (l'idée de Louis)

**Le saut quantique** : passer de *"décris ton projet en mots"* à *"file-moi l'URL de ton repo, je l'analyse"*.

### UX cible

```
Utilisateur :  https://github.com/louis/mon-projet-fastapi-mlflow

Bot :          [Cloning... 3s]
               [Analyse en cours...]

               ## Couverture RNCP détectée

               ### Techs détectées (auto)
               - FastAPI 0.110 (pyproject.toml)
               - Docker (Dockerfile présent)
               - pytest + 47 tests (coverage 78%)
               - GitHub Actions (.github/workflows/ci.yml)
               - MLflow 2.8 (imports détectés)
               - Prometheus exporters (requirements)

               ### Compétences validées (12/21)
               ✅ C5  — API REST FastAPI (preuve : src/api/main.py:23)
               ✅ C11 — Monitoring (preuve : src/monitoring/prometheus.py)
               ...
```

### Comment l'implémenter

| Étape | Outil |
|-------|-------|
| Récupérer le repo | `git clone --depth 1` ou GitHub API tree |
| Lister les fichiers de config | `Dockerfile`, `pyproject.toml`, `package.json`, `*.yml`, `Makefile` |
| Détection techs par patterns | regex sur imports, parse TOML/YAML |
| Vérif tests | `pytest --collect-only`, lecture des badges CI |
| Lire le README | extraire la description |
| Tout passer en input du RAG | concat des findings → prompt |

### Effort estimé : 1-2 jours

**Lib utiles** : `gitpython`, `tree-sitter` (parse multi-langage), `tomllib` (Python 3.11+).

---

## 🚀 Idée 2 — Plan d'action chiffré (génération de roadmap)

Au lieu de juste dire *"C18 manque"*, le bot répond :

```
## Pour valider 3 compétences supplémentaires :

### C18 (Tests automatisés) — effort estimé : 4h
1. Ajouter `pytest-cov` à requirements.txt
2. Créer `tests/test_api.py` avec au moins 5 tests
3. Activer le badge coverage dans le README
4. Au prochain push, C18 sera validée

### C19 (Livraison continue application) — effort estimé : 2h
1. Compléter `.github/workflows/deploy.yml`
2. Ajouter un environnement staging
3. ...

### C20 (Surveillance application) — effort estimé : 6h
1. ...
```

**Implémentation** : prompt enrichi qui demande au LLM de produire un plan d'action structuré.

---

## 📊 Idée 3 — Suivi temporel d'un projet

Le bot mémorise les analyses passées et trace l'**évolution de la couverture** :

```
Promo Dev IA 2026 — Projet "MonProjet"

Mar 1   ████ 4/21 (19%) — Phase data
Mar 15  ████████ 8/21 (38%) — API ajoutée
Apr 1   ████████████ 12/21 (57%) — CI/CD
Apr 10  ██████████████ 15/21 (71%) — Monitoring
                ▲ aujourd'hui
                Encore C8, C13, C16, C18, C20, C21 à valider avant soutenance
```

**Implémentation** : Storage minimal (SQLite ou JSON) avec snapshots datés. Memory layer style mem0/Zep.

---

## 🎓 Idée 4 — Mode "entretien jury" (préparation soutenance)

Le bot **simule un jury** et pose des questions techniques sur le projet :

```
Bot : J'ai analysé ton projet. Pour C13, ton CI/CD utilise Docker mais pas de
      packaging du modèle. Question : pourquoi le Dockerfile copie-t-il les
      poids du modèle directement plutôt que d'utiliser MLflow Model Registry ?

User : (réponse)

Bot : Bonne réponse. Suivi : si on ajoutait un système de drift detection,
      quelle compétence supplémentaire viserais-tu ?
```

**Pédagogiquement** : c'est ce qui MANQUE le plus aux apprenants. Faire un produit qui **prépare à la soutenance** est très différenciant.

---

## 🔁 Idée 5 — GitHub Action "RNCP Coverage Bot"

À chaque PR, un bot commente :

```
🤖 RNCP Dev IA Coverage Report

Cette PR ajoute :
  + C13 (CI/CD modèle IA) — détecté via le nouveau workflow MLOps
  + C18 (tests automatisés) — 12 nouveaux tests pytest

Couverture totale : 14/21 (67%) ↑ +2 vs main

⚠️ Attention : tu as ajouté du code FastAPI sans test unitaire.
   → Suggestion : ajouter tests/test_api.py pour solidifier C18.
```

**Implémentation** : action Docker qui appelle l'API du chatbot. Marketplace GitHub Action.

---

## 🏫 Idée 6 — Mode formateur : analyse d'une promo entière

Un formateur upload une liste de 30 repos GitHub. Le bot génère :

```
Promo Dev IA — Avril 2026

Statistiques :
- Couverture moyenne : 14.3 / 21 compétences
- Compétence la plus validée : C5 (95%)
- Compétence la moins validée : C13 (32%)
- Apprenants à risque (< 12/21) : Alice, Bob, Carol

Détails par apprenant :
[tableau exportable CSV/PDF]
```

**Use case** : énorme gain de temps pour les formateurs Simplon.

---

## 🌐 Idée 7 — Multi-référentiel (RNCP + autres)

Pas que Dev IA — supporter :
- RNCP Développeur Web
- RNCP Data Engineer
- Référentiels internes Simplon (modules)
- Référentiels d'autres écoles (OpenClassrooms, Le Wagon, etc.)

**Implémentation** : un dataset HF par référentiel, choix au démarrage de la session.

---

## 🤖 Idée 8 — Score de confiance par compétence (RAGAS)

Pour chaque compétence identifiée, afficher un **score de confiance** :

```
✅ C5  — API REST            confiance 95% ████████████████████
✅ C11 — Monitoring          confiance 87% █████████████████░░
⚠️  C13 — Livraison continue confiance 62% ████████████░░░░░░░░
   (à confirmer manuellement)
```

**Implémentation** : multi-LLM voting (Mistral + Claude + GPT) avec consensus, ou métrique de cohérence du retrieval.

---

## 📦 Idée 9 — Génération de rapport PDF

Le bot génère un **rapport officiel** que l'apprenant peut joindre à son dossier de soutenance :

```
[Rapport de couverture RNCP — 2026-04-30]
- Page 1 : Synthèse exécutive
- Page 2-3 : Détail par compétence avec citations
- Page 4 : Roadmap des compétences manquantes
- Page 5 : Métadonnées (commit hash, date analyse)
```

**Lib** : WeasyPrint (Python → PDF) ou Pandoc.

---

## 🧠 Idée 10 — Memory persistante par utilisateur

Chaque apprenant a un compte et le bot **se souvient** de :
- Ses projets précédents
- Ses lacunes récurrentes
- Ses préférences (vocabulaire, tone)
- Les conseils déjà donnés

**Implémentation** : mem0 / Letta / claude-mem.

---

## 📡 Idée 11 — Live coding session avec le bot

Pendant que l'apprenant code, le bot **observe en direct** (via une extension VS Code) et signale en temps réel :

```
[VS Code extension popup]
"Tu viens d'ajouter un Dockerfile + un workflow GitHub Actions.
 → C13 et C18 viennent de passer en VALIDÉES (provisoirement).
 Continue !"
```

**Use case** : feedback loop immédiat = motivation +++ pour l'apprenant.

---

## 🎯 Priorisation par impact / effort

| # | Idée | Impact | Effort | Priorité |
|---|------|--------|--------|----------|
| 1 | Analyse repo GitHub | 🔥🔥🔥 | 1-2j | **V2.0** |
| 2 | Plan d'action chiffré | 🔥🔥🔥 | 4h | **V2.0** |
| 4 | Mode entretien jury | 🔥🔥🔥 | 2-3j | **V2.1** |
| 9 | Génération PDF | 🔥🔥 | 1j | **V2.1** |
| 8 | Score confiance | 🔥🔥 | 2j | **V2.1** |
| 3 | Suivi temporel | 🔥🔥 | 3j | **V3.0** |
| 5 | GitHub Action | 🔥🔥 | 3j | **V3.0** |
| 7 | Multi-référentiel | 🔥🔥 | 2j | **V3.0** |
| 6 | Mode formateur batch | 🔥 | 2j | **V3.0** |
| 10 | Memory utilisateur | 🔥 | 3j | **V4.0** |
| 11 | Extension VS Code | 🔥🔥 | 5-7j | **V5.0** |

## 💡 Recommandation

**V2.0 (post-soutenance)** : Idées **1 + 2** (analyse repo + plan d'action) → impact massif, effort raisonnable, transforme l'outil en **vrai produit utilisable**.

**Pitch unique value proposition V2** :
> *"L'apprenant donne l'URL de son repo, le bot lui rend en 30s un rapport PDF avec ses compétences validées + un plan d'action chiffré pour les compétences manquantes — directement utilisable pour son dossier de soutenance."*

**V3.0 (industrialisation)** : Idée **5 + 6** (GitHub Action + mode formateur) → adoption par toute une école.

**V5.0 (différenciation)** : Idée **11** (extension VS Code) → outil quotidien des apprenants.
