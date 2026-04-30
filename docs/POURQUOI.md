# Pourquoi cet outil ? Vision produit

> **TL;DR** — On part d'un problème concret des apprenants Simplon (savoir où ils en sont sur leurs 21 compétences RNCP) et on construit un outil qui transforme cette question en 30 secondes via leur URL GitHub.

---

## 🩹 Le problème qu'on résout

Tout apprenant Simplon "Développeur en IA" doit valider **21 compétences** (C1-C21) sur 3 blocs avant la soutenance. Aujourd'hui :

- **Le référentiel est un PDF de 23 pages** dense, écrit en jargon France Compétences
- **Aucun outil** ne dit *"voici ce que ton projet couvre vs ce qu'il manque"*
- **Les apprenants tâtonnent** : *"Est-ce que mon Dockerfile suffit pour C13 ?"*, *"Il me manque quoi pour le bloc MLOps ?"*
- **Les formateurs perdent du temps** à répondre 30× la même question
- **Les rendus sont inégaux** : sans grille commune, certains projets sur-vendent leurs compétences, d'autres les sous-vendent

C'est un problème **réel, mesurable, récurrent** — exactement le profil d'usage où un assistant IA spécialisé apporte de la valeur.

---

## 🎯 Ce que l'outil fait (V1, livré)

Un chatbot RAG qui :

1. **Indexe** le référentiel officiel par compétence (1 chunk par C1 à C21)
2. **Reçoit** soit une description en langage naturel, soit une **URL GitHub**
3. **Identifie** les compétences couvertes avec **citation textuelle exacte**
4. **Liste** ce qui manque, avec un **plan d'action chiffré** (V2)
5. **Cite** ses sources (numéro de page, extrait du référentiel)

Stack 2026 état de l'art : Mistral (souveraineté EU) + Qdrant + LangChain + reranker bge-reranker-v2-m3 + Chainlit. Déployé sur HF Spaces (URL publique gratuite).

---

## 🌟 Ce qu'on veut en V2+ (ce vers quoi on va)

### Court terme (V2 — 1 mois)

- **Analyse repo GitHub** ✅ *(déjà livré dans la même session)* → l'apprenant colle son URL, le bot clone, détecte les technos, et analyse
- **Plan d'action chiffré** ✅ *(idem)* → "pour valider C18, ajoute pytest + 5 tests = ~4h"
- **Rapport PDF téléchargeable** → joignable au dossier de soutenance comme preuve
- **Mode "entretien jury"** → le bot pose des questions techniques sur le projet, simule le jury

### Moyen terme (V3 — 3 mois)

- **GitHub Action "RNCP Coverage Bot"** → à chaque PR, un bot commente avec le delta de couverture
- **Mode formateur** → upload d'une liste de 30 repos d'une promo, dashboard agrégé, détection des apprenants à risque
- **Multi-référentiel** → pas que Dev IA, aussi Dev Web, Data Engineer, etc.

### Long terme (V4-V5)

- **Memory persistante par utilisateur** (mem0/Letta) → le bot se souvient des projets précédents et des conseils déjà donnés
- **Extension VS Code** → analyse en live pendant que l'apprenant code : *"Tu viens d'ajouter un Dockerfile + un workflow → C13 et C18 viennent de passer en validé. Continue !"*

---

## 💡 Ce qui rend cet outil différent d'un ChatGPT générique

### 1. Citations sourcées vérifiables
ChatGPT aurait donné une réponse plausible mais sans citation. Notre bot dit *"C13 est validé, voir page 4 du référentiel : 'Créer une chaîne de livraison continue…'"*. **Un apprenant peut joindre cette réponse à son dossier de soutenance comme preuve documentée.**

### 2. Lecture stricte du référentiel officiel
On ne devine pas ce qu'est "le bloc MLOps" — on cite la page 4 du PDF Simplon mot pour mot.

### 3. Spécifique à un cas d'usage
L'analyse de repo GitHub auto, le plan d'action chiffré, la synthèse par bloc — tout est calibré pour un apprenant Simplon en préparation de soutenance.

### 4. Souveraineté EU
LLM Mistral (Paris), embeddings Mistral, hébergement HF (UE). Pas de données qui partent chez OpenAI.

### 5. Honnêteté intellectuelle assumée
Les limitations sont **documentées** (`vault/decisions/`, `docs/scenarios-demo.md`). On ne survend pas. C'est important pour un outil pédagogique.

---

## 🧠 Ce qu'on a appris en construisant ça (et qui se transfère)

- **Le pattern triplet retrieval 2026** : hybrid search + cross-encoder reranking → retrieval state-of-the-art
- **Le prompt système est ~80% de la qualité** d'un RAG
- **Les bugs upstream se corrigent** (LangChain #22556 fixé proprement par sous-classe)
- **Le "RAG is dead" est nuancé** : pour des sources privées, citables, à faible latence, RAG reste pertinent
- **Le déploiement HF Spaces a des pièges** (`huggingface_hub` lit le `.gitignore` distant silencieusement, force-push écrase les commits XET du PDF, etc.) — documenté dans `docs/deploy-hf.md`

---

## 🎓 Pourquoi c'est un projet de soutenance défendable

Cet outil **utilise lui-même** beaucoup des compétences du référentiel qu'il analyse :

| Compétence | Appliquée ici |
|------------|---------------|
| C5 (API REST) | Chainlit expose une API web |
| C9 (API IA) | Wrapper Mistral + Qdrant via LangChain |
| C10 (intégration API IA) | mistral-small-latest intégré |
| C13 (CI/CD modèle) | GitHub Actions sur push/PR |
| C18 (tests automatisés) | 8 tests pytest, lint Ruff, format check |
| C20 (monitoring) | Logging structuré, healthcheck Docker |

**Méta-niveau** : tu construis un outil qui mesure les compétences RNCP, en utilisant les compétences RNCP. C'est exactement ce que France Compétences appelle un projet *intégrateur*.
