# Notes de soutenance — Chatbot RAG RNCP Dev IA

> Aide-mémoire pour la soutenance. À relire la veille.

---

## 🎯 Pitch en 30 secondes

> *"J'ai construit un chatbot RAG qui analyse la couverture du référentiel RNCP Dev IA par un projet décrit en langage naturel. L'utilisateur décrit son projet, le bot identifie les compétences validées avec citations textuelles du référentiel, et liste celles qui manquent. Stack : Mistral, Qdrant, LangChain, Chainlit. Déployé en live sur Hugging Face Spaces — accessible sans installation."*

---

## 🏗️ Architecture en une phrase

**Pipeline 2026 état de l'art** : ingestion PDF par compétence → indexation hybride (BM25 + dense via Mistral) → retrieval **hybrid + cross-encoder reranking** → génération avec citations.

```
PDF → split par compétence (regex C1-C21)
    → indexation Qdrant (Mistral embed) + corpus BM25
        → question utilisateur
            → BM25 (k=15) + Qdrant (k=15) → EnsembleRetriever (RRF, weights=0.4/0.6)
                → CrossEncoderReranker bge-reranker-v2-m3 (top_n=10)
                    → ChatPromptTemplate + ChatMistralAI (temp=0)
                        → réponse markdown + sources affichées
```

---

## 🛡️ Justifications techniques (questions piège du jury)

### "Pourquoi Mistral et pas OpenAI ?"
- Souveraineté EU (RGPD, hébergement français)
- Coût maîtrisé pour un projet pédagogique
- Performance FR native (mistral-embed multilingue)
- Crédit gratuit dispo pour étudiants (plan Experiment)
- Pas de carte bancaire requise

### "Pourquoi Qdrant et pas Chroma/Weaviate/PGVector ?"
- Hybrid search **natif** (BM25 + dense ensemble) sans bricolage
- Filtres metadata performants (utile pour filtrer par bloc de compétences)
- Persistence auto sur disque, mode in-memory disponible (utile HF Spaces)
- Open source, Rust, performant

### "Pourquoi un cross-encoder reranker ?"
- mistral-embed seul ne discrimine pas bien les codes courts (C5 vs C15)
- BM25 capte le lexical (mot exact "FastAPI"), dense capte la paraphrase
- Le cross-encoder calcule un score sur la **paire (question, chunk)** → beaucoup plus précis qu'une similarité cosinus brute
- bge-reranker-v2-m3 : multilingue (FR), poids 1.1 GB, viable en CPU

### "Pourquoi `temperature=0` ?"
- Anti-hallucination créative
- Déterminisme : la même question → la même réponse
- On veut un bot factuel, pas créatif

### "Pourquoi `score_threshold=0.4` (et plus k=4 simple) ?"
- Anti-hallucination sur questions hors-sujet (ex: "tu connais Pokemon ?")
- Si aucun chunk dépasse 0.4, le retriever renvoie liste vide → le prompt force le LLM à dire "hors scope"
- *Note* : depuis le pivot vers le pattern reranker, le score_threshold est moins critique car le reranker filtre déjà les non-pertinents.

### "Pourquoi splitter par compétence (et pas RecursiveCharacterTextSplitter classique) ?"
- Le PDF est structuré : chaque compétence Cn est un bloc cohérent
- Splitter classique coupait au milieu des libellés → retrieval pourri
- Regex `(?=^C\d+\.\s)` avec MULTILINE → un chunk par compétence
- Filtrage `LIBELLE_PAGES = {4, 5}` pour ne garder que les libellés purs (pas la table des matières)

---

## 🐛 Bugs résolus (à raconter — preuve que tu lis le code)

### 1. Bug LangChain upstream #22556 (le plus impressionnant)
- **Symptôme** : tous les scores affichés étaient `0.00` malgré le reranker fonctionnel
- **Diagnostic** : lecture du code source `langchain.retrievers.document_compressors.CrossEncoderReranker.compress_documents` → les scores sont calculés pour le tri puis **jetés** avant retour
- **Fix** : sous-classe `ScoringCrossEncoderReranker` qui injecte `score` dans `metadata['relevance_score']` avant le slicing
- **Bonus** : application d'une sigmoid pour normaliser les logits bruts en probabilité [0,1]
- **À montrer** : `src/chain.py:208-235` + tests unitaires

### 2. Bug `huggingface_hub.upload_file()` silent filter
- **Symptôme** : upload du PDF "succès" (URL retournée), mais 404 au runtime
- **Diagnostic** : `huggingface_hub` ≥ 0.21 lit le `.gitignore` distant et drop silencieusement les fichiers qui matchent
- **Fix** : commenter `data/*.pdf` dans `.gitignore` sur la branche `hf-deploy` uniquement
- **À montrer** : `docs/deploy-hf.md`

### 3. PyMuPDF vs pypdf
- **Symptôme** : pypdf perdait les espaces sur le PDF Simplon → texte illisible → retrieval à côté de la plaque
- **Fix** : switch vers PyMuPDF (extraction layout-aware)
- **Leçon** : ne pas faire confiance aveuglément au parser par défaut

### 4. Pré-warm du reranker au boot
- **Problème** : 1ère requête utilisateur déclenchait téléchargement + chargement reranker = ~30s d'attente
- **Fix** : `app.py` charge `_get_reranker_model()` + `_get_bm25_retriever()` au module load (avant que Chainlit accepte le 1er message)
- **Résultat** : 1er message instantané

### 5. Latence 164s → 11.5s
- **Diagnostic** : `retrieve_with_scores()` était appelée DEUX fois (une pour les sources, une dans la chain)
- **Fix** : externalisation du retrieval hors de la chain LCEL → un seul appel reranker par message
- **Leçon** : profiler avant d'optimiser

---

## 📊 Métriques à donner si demandé

| Métrique | Valeur |
|----------|--------|
| Chunks indexés | 21 (un par compétence) |
| Modèle embedding | mistral-embed (1024 dim) |
| Modèle reranker | BAAI/bge-reranker-v2-m3 (1.1 GB) |
| Top-k retriever | 15 (BM25) + 15 (Qdrant) = 30 candidats |
| Top-n reranker final | 10 chunks envoyés au LLM |
| Latence par message | 10-15s (CPU, HF Spaces gratuit) |
| Cold start container | ~10-15s (indexation in-memory + chargement reranker) |
| Coût estimé / 1000 questions | ~0.20€ Mistral (small + embed) |

---

## 🚧 Limitations assumées (à dire AVANT que le jury demande)

1. **Pas de tests d'intégration end-to-end** : on teste les fonctions pures (split, format) mais pas de roundtrip complet avec Mistral réel — coûteux en tokens et fragile (clé API, rate limit)
2. **Persistence Qdrant absente sur HF** : mode in-memory → réindexation à chaque restart container (OK pour 21 chunks, pas pour 10000+)
3. **Latence CPU 10-15s** : pourrait passer à 2-3s sur GPU T4, ou ~5s avec un reranker plus léger (bge-reranker-base)
4. **Pas de memory utilisateur** : chaque session repart de zéro, pas de mémoire persistante (V4)
5. **Référentiel mono-source** : aujourd'hui Dev IA uniquement, à étendre (V3)

---

## 🌟 Pitch unique value (à différencier d'un ChatGPT générique)

> *"Un ChatGPT générique pourrait répondre, mais avec hallucinations et sans citation vérifiable. Mon bot cite les passages exacts du référentiel officiel — un apprenant peut joindre la réponse à son dossier de soutenance comme **preuve documentée**."*

---

## 🔮 Roadmap V2+ (montrer que tu as une vision produit)

**V2.0** (post-soutenance, 1-2 jours) : analyse automatique d'un repo GitHub. *"Donne l'URL de ton repo, le bot le clone, détecte les techs, rend le rapport"*. Couplé à la génération d'un plan d'action chiffré pour les compétences manquantes.

**V3.0** : GitHub Action commentant chaque PR avec couverture RNCP, mode formateur batch (analyse 30 repos d'une promo).

**V5.0** : extension VS Code qui analyse en live pendant que l'apprenant code.

→ détails dans `vault/ideas/v2-roadmap-improvements.md`.

---

## 🎓 Réponses aux questions piège prévisibles

### "RAG c'est mort, non ? Karpathy a fait sa LLM Wiki sans RAG."
- Vrai débat 2026, mais nuance importante :
  - LLM Wiki de Karpathy = base de connaissances **statique**, **publique**, déjà connue du modèle pré-entraîné
  - Mon use case = source **privée** (référentiel Simplon), **citations vérifiables** obligatoires
- Anthropic Claude Code utilise une approche **agentic search** (parcourt le filesystem au runtime) — efficace pour du code, moins pour un PDF de 23 pages
- Conclusion : RAG reste pertinent quand on a besoin de **citations sourcées + faible latence + corpus mono-source**

### "Pourquoi pas du fine-tuning ?"
- Coût : 100-1000€ pour fine-tune sur ce corpus, vs 0€ pour RAG
- Update : si le référentiel change, RAG = ré-indexer en 2 min ; fine-tune = re-train
- Citations : un modèle fine-tuné ne sait pas dire "voici la phrase exacte"
- **Bon use case fine-tuning** : style/persona, pas knowledge

### "Pourquoi pas un système de tools (web search) ?"
- Approche valide mais latence augmente (tool call → search API → parsing → LLM call)
- Mon référentiel est figé en local, donc retrieval direct sur Qdrant > web search
- En V2, on pourrait ajouter LangGraph pour router : RAG si question référentiel, tool search si question hors-scope

### "Comment évalues-tu la qualité ?"
- **Honnêteté** : pas d'évaluation systématique automatisée pour ce MVP
- 3 scénarios de référence dans `docs/scenarios-demo.md` testés manuellement
- En V2 : RAGAS (faithfulness, answer relevance, context precision/recall) + Langfuse pour observability

### "Et si Mistral down ?"
- Le pipeline reste fonctionnel jusqu'au LLM (retrieval marche)
- Fallback possible : switch vers ChatOllama (Llama 3.1) en local
- Architecture LangChain abstrait le LLM, change facilement

---

## ✅ Checklist finale avant soutenance

- [ ] Tester le HF Space en live 1h avant la soutenance (le Space dort après 24h sans traffic)
- [ ] Préparer 3 questions de référence pour la démo live
- [ ] Avoir le code ouvert dans VS Code, pas les diapos uniquement
- [ ] Connaitre les chiffres clés (latence, k, threshold, coût)
- [ ] Avoir un récit pour CHAQUE bug fixé (#22556 surtout)
- [ ] Ne pas survendre — assumer les limitations explicitement
