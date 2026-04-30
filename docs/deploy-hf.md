# Déploiement Hugging Face Spaces

> Documentation du déploiement public du chatbot sur Hugging Face Spaces.
> Bonus du brief Simplon ("URL publique accessible sans installation").

## 🌐 URLs

- **Space (admin)** : https://huggingface.co/spaces/centau/chatbot-rncp-dev-ia
- **App live** : https://centau-chatbot-rncp-dev-ia.hf.space

## 🏗️ Architecture du déploiement

```
GitHub repo (main)                    HF Space (centau/chatbot-rncp-dev-ia)
   │                                       │
   │  branche `hf-deploy` (ne merge pas)   │  Docker SDK + Xet pour binaires
   ├──────────────────────────────────────►│
   │                                       │
   │  + PDF uploadé via huggingface_hub    │  Image Docker construite par HF
   │    (API Xet, hors git)                │  → Container exécuté sur cpu-basic
   │                                       │  → URL publique disponible
```

La branche `hf-deploy` contient des **adaptations spécifiques HF Spaces** qu'on
ne veut pas merger dans `main` (qui reste optimisé pour le dev local avec Qdrant
en sidecar).

## 🔧 Adaptations sur la branche `hf-deploy`

| Fichier | Modification | Pourquoi |
|---------|--------------|----------|
| `Dockerfile` | Port 7860 (au lieu de 8000) | Convention HF Spaces |
| `Dockerfile` | `ENV QDRANT_URL=:memory:` | Pas de service Qdrant externe en HF |
| `Dockerfile` | `RUN python -c "CrossEncoder(...)"` | Pré-télécharge bge-reranker-v2-m3 (1.1 GB) en build pour éviter les 30s du 1er run |
| `src/config.py` | Flag `QDRANT_IN_MEMORY` | Active l'auto-indexation au boot |
| `src/chain.py` | Singleton `get_qdrant_client()` | **Critique** en in-memory : on doit partager le même client entre ingestion et retrieval (sinon vecteurs invisibles) |
| `src/ingest.py` | `ensure_indexed_in_memory()` | Réindexe le PDF au démarrage du container (in-memory = pas de persistence) |
| `app.py` | Pré-warm complet au chargement du module | Appel à `ensure_indexed_in_memory()` + reranker + BM25 avant que Chainlit accepte un message |
| `README.md` | Frontmatter YAML HF Spaces | `sdk: docker`, `app_port: 7860`, `short_description`, etc. |

## 📦 Comment HF gère les binaires (et le piège qu'on a découvert)

HF Spaces utilise **Xet** (leur système propriétaire de stockage des binaires,
remplaçant LFS depuis mai 2025). Activé par défaut sur tous les nouveaux Spaces.

### ⚠️ Piège : `huggingface_hub.upload_file()` respecte le `.gitignore` distant

**Comportement non documenté en évidence** : depuis `huggingface_hub` 0.21+,
`upload_file()` lit le `.gitignore` du repo distant et **drop silencieusement**
les fichiers qui matchent un pattern, **sans renvoyer d'erreur**. Le commit est
créé (avec une URL retournée), mais le fichier n'est PAS dans le tree.

**Symptôme observé sur ce projet** :
- Notre `.gitignore` contenait `data/*.pdf` (pour ne pas commiter le PDF dans `main`)
- Sur la branche `hf-deploy`, on uploadait le PDF via `upload_file()`
- L'API retournait succès → mais `list_repo_files()` ne montrait pas le PDF
- HEAD sur `https://huggingface.co/spaces/.../resolve/main/data/...pdf` → **404**

### Solution

Sur la branche `hf-deploy`, on **commente** la règle `data/*.pdf` du `.gitignore` :

```diff
- data/*.pdf
+ # data/*.pdf  (commenté volontairement sur hf-deploy)
```

Puis on uploade le PDF via l'API qui passe automatiquement par Xet :

```python
from huggingface_hub import upload_file

upload_file(
    path_or_fileobj="data/referentiel-rncp-dev-ia.pdf",
    path_in_repo="data/referentiel-rncp-dev-ia.pdf",
    repo_id="centau/chatbot-rncp-dev-ia",
    repo_type="space",
    token=HF_TOKEN,
)
```

Le PDF est dans le repo Space mais **pas dans le build context Docker** (Xet
stocke les binaires hors-git). Donc on le télécharge au runtime via
`hf_hub_download()` dans `ensure_indexed_in_memory()`.

### Note sur le push git

`git push` direct rejette les binaires non-Xet (message "Please use Xet").
Pour push des binaires en git, il faudrait installer
[git-xet](https://huggingface.co/docs/hub/en/xet/using-xet-storage#git).
On préfère passer par l'API qui gère ça toute seule.

## 🔐 Secrets (MISTRAL_API_KEY)

Configuré côté HF via l'API REST (pas de CLI nécessaire) :

```bash
curl -X POST "https://huggingface.co/api/spaces/centau/chatbot-rncp-dev-ia/secrets" \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"key\": \"MISTRAL_API_KEY\", \"value\": \"$MISTRAL_API_KEY\"}"
```

Le secret est injecté en variable d'environnement dans le container.
**Jamais commité, jamais visible dans les logs.**

## ⚙️ Caractéristiques du container

| Param | Valeur |
|-------|--------|
| **Hardware** | cpu-basic (gratuit, 16 GB RAM) |
| **Image taille** | ~3.5 GB (Python + venv + reranker pré-téléchargé) |
| **Cold start** | ~10-15s (indexation in-memory du PDF + chargement reranker) |
| **Latence par message** | 10-15s (idem qu'en local) |
| **Persistence** | ⚠️ Aucune (Qdrant in-memory) — l'index se reconstruit à chaque restart |

## 🚀 Comment redéployer (mise à jour du code)

```bash
git checkout hf-deploy
# faire les modifs sur cette branche uniquement
git add ...
git commit -m "..."
git push hf hf-deploy:main
# (le push relance automatiquement le build HF)
```

⚠️ **Si on modifie le PDF**, il faut le re-uploader manuellement via l'API HF
(le push git n'inclut pas le PDF qui est en Xet).

## 🔄 Comment ramener les modifs hf-deploy dans main (déconseillé)

**Surtout pas !** Les modifs hf-deploy cassent le dev local :
- Port 7860 au lieu de 8000
- `QDRANT_URL=:memory:` désactive le Qdrant local Docker
- L'auto-indexation au boot est inutile en local

→ La séparation `main` (dev local) / `hf-deploy` (déploiement HF) est volontaire.

## 🧪 Vérifier l'état du Space

```bash
# Stage du build (BUILDING / RUNNING / SLEEPING / ERROR)
curl -s -H "Authorization: Bearer $HF_TOKEN" \
  https://huggingface.co/api/spaces/centau/chatbot-rncp-dev-ia | \
  jq '.runtime.stage'

# Logs en temps réel : aller sur https://huggingface.co/spaces/centau/chatbot-rncp-dev-ia/logs
```

## 📊 Points soutenance liés au déploiement

À mentionner si questions sur le déploiement :

1. **Pourquoi HF Spaces** : gratuit, pas d'inscription pour l'utilisateur final, intégration Docker simple
2. **Pourquoi pas Cloud Run/Azure** : nécessite carte bancaire, IAM complexe pour un projet d'apprentissage
3. **Limite cpu-basic** : reranker `bge-reranker-v2-m3` (1.1 GB) tient dans 16 GB de RAM mais latence ~3-5s en CPU
4. **Évolution prod** : passer en GPU T4 ou switcher vers `bge-reranker-base` (3-4× plus rapide en CPU)
5. **Pas de persistence Qdrant** : indexation au boot OK pour 21 chunks (1-2s), problématique pour 10000+ chunks → migration Qdrant Cloud nécessaire
