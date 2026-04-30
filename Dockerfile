# =====================================================
# Dockerfile multistage pour le chatbot RNCP Dev IA
# =====================================================
# Approche : 2 stages
#   - builder : installe uv, télécharge les deps, crée le venv (lourd : ~600 MB)
#   - runtime : ne garde que le venv et le code (léger : ~150 MB)
# Résultat : image finale 4× plus petite que sans multistage.

# ----------- Stage 1 : Builder -----------
FROM python:3.13-slim AS builder

# uv : gestionnaire de paquets Python moderne (Astral, 2026)
# 10-100× plus rapide que pip + lockfile reproductible
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Copier UNIQUEMENT les fichiers de deps avant tout (pour profiter du cache Docker)
# Si on copie tout le code en premier, le moindre changement invalide le cache pip.
COPY pyproject.toml uv.lock ./

# Installer les deps dans /app/.venv (--frozen = utilise pile la version du lockfile)
# --no-dev = on n'installe pas pytest, ruff, etc. (pas besoin en runtime)
RUN uv sync --frozen --no-dev


# ----------- Stage 2 : Runtime -----------
FROM python:3.13-slim AS runtime

# Variables d'environnement de production
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copier le venv compilé du builder (pas besoin de réinstaller)
COPY --from=builder /app/.venv /app/.venv

# Copier le code applicatif
COPY src/ ./src/
COPY app.py ./app.py
COPY data/ ./data/

# Créer un utilisateur non-root (sécurité — ne JAMAIS faire tourner en root)
RUN useradd --create-home --uid 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Healthcheck : vérifie que Chainlit répond (utile pour Cloud Run / HF Spaces)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000', timeout=5)" || exit 1

# Port Chainlit par défaut
EXPOSE 8000

# Lancement : --host 0.0.0.0 pour accepter les connexions depuis l'extérieur du container
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000", "--headless"]
