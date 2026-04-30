"""Analyse automatique d'un repo GitHub — V2 idée 1.

Donne une URL GitHub, le module clone le repo (shallow), détecte les
technologies utilisées via les fichiers de config, et produit un résumé
structuré qu'on peut passer au pipeline RAG existant comme description
de projet.

UX cible :
    >>> summary = analyze_repo("https://github.com/user/projet-fastapi")
    >>> print(summary)
    Repo : user/projet-fastapi
    Description (README) : ...
    Technologies détectées :
    - FastAPI 0.110 (pyproject.toml)
    - Docker (Dockerfile présent)
    - pytest (deps + tests/)
    - GitHub Actions (.github/workflows/ci.yml)
    Structure principale : src/, tests/, docs/

Ce résumé est ensuite passé à `retrieve_with_scores()` puis à la chain RAG
comme s'il s'agissait d'une description en langage naturel — réutilisation
totale du pipeline existant, zéro modification de chain.py.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


# Pattern d'URL GitHub valide (org/user + repo). Non-ancré pour matcher au milieu d'un texte.
# Greedy sur le nom du repo pour capter les tirets (chatbot-rncp-dev-ia, etc.).
# Le `.git` final ou `/tree/branch` est traité par `extract_github_url` qui nettoie.
GITHUB_URL_PATTERN = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)")

# Mapping technologie → patterns de détection
# (regex, où chercher) — la regex matche dans le contenu du fichier ciblé.
TECH_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "FastAPI": [(r"\bfastapi\b", "pyproject.toml"), (r"\bfastapi\b", "requirements.txt")],
    "Flask": [(r"\bflask\b", "pyproject.toml"), (r"\bflask\b", "requirements.txt")],
    "Django": [(r"\bdjango\b", "pyproject.toml"), (r"\bdjango\b", "requirements.txt")],
    "Streamlit": [(r"\bstreamlit\b", "pyproject.toml"), (r"\bstreamlit\b", "requirements.txt")],
    "Gradio": [(r"\bgradio\b", "pyproject.toml"), (r"\bgradio\b", "requirements.txt")],
    "Chainlit": [(r"\bchainlit\b", "pyproject.toml"), (r"\bchainlit\b", "requirements.txt")],
    "MLflow": [(r"\bmlflow\b", "pyproject.toml"), (r"\bmlflow\b", "requirements.txt")],
    "scikit-learn": [
        (r"scikit[-_]learn", "pyproject.toml"),
        (r"scikit[-_]learn", "requirements.txt"),
    ],
    "PyTorch": [(r"\btorch\b", "pyproject.toml"), (r"\btorch\b", "requirements.txt")],
    "TensorFlow": [(r"tensorflow", "pyproject.toml"), (r"tensorflow", "requirements.txt")],
    "LangChain": [(r"langchain", "pyproject.toml"), (r"langchain", "requirements.txt")],
    "Prometheus": [
        (r"prometheus[-_]client", "pyproject.toml"),
        (r"prometheus[-_]client", "requirements.txt"),
    ],
    "pytest": [(r"\bpytest\b", "pyproject.toml"), (r"\bpytest\b", "requirements.txt")],
    "Qdrant": [(r"qdrant", "pyproject.toml"), (r"qdrant", "requirements.txt")],
    "OpenAI API": [(r"\bopenai\b", "pyproject.toml"), (r"\bopenai\b", "requirements.txt")],
    "Mistral API": [(r"mistralai", "pyproject.toml"), (r"mistralai", "requirements.txt")],
}

# Fichiers de configuration whose simple presence indique une techno
PRESENCE_INDICATORS: dict[str, str] = {
    "Docker": "Dockerfile",
    "Docker Compose": "docker-compose.yml",
    "GitHub Actions": ".github/workflows",
    "pre-commit hooks": ".pre-commit-config.yaml",
    "Makefile": "Makefile",
    "uv (Astral)": "uv.lock",
    "Poetry": "poetry.lock",
    "Node.js": "package.json",
    "Terraform": "main.tf",
    "Kubernetes": "k8s",
}


@dataclass
class RepoAnalysis:
    """Résultat structuré d'une analyse de repo."""

    org: str
    repo: str
    description: str = ""
    techs: list[str] = field(default_factory=list)
    has_tests: bool = False
    structure: list[str] = field(default_factory=list)

    def to_natural_language(self) -> str:
        """Format le résultat comme une description de projet en français.

        Cette représentation est conçue pour être passée directement au
        pipeline RAG existant — le chatbot l'analysera comme s'il s'agissait
        d'une description tapée par l'utilisateur.
        """
        lines = [f"Projet GitHub : {self.org}/{self.repo}"]

        if self.description:
            lines.append(f"\nDescription (extraite du README) :\n{self.description}")

        if self.techs:
            lines.append("\nTechnologies et outils détectés :")
            lines.extend(f"- {t}" for t in self.techs)

        if self.has_tests:
            lines.append(
                "\nLe projet contient des tests automatisés (dossier tests/ ou test_*.py)."
            )

        if self.structure:
            lines.append(f"\nStructure principale du projet : {', '.join(self.structure)}")

        return "\n".join(lines)


def extract_github_url(text: str) -> str | None:
    """Trouve la première URL GitHub valide dans `text`, ou None."""
    for match in GITHUB_URL_PATTERN.finditer(text):
        return match.group(0).rstrip("/").removesuffix(".git")
    return None


def _shallow_clone(url: str, target: Path) -> None:
    """Clone superficiel (depth=1) — minimise la bande passante et le temps.

    Pour les repos PRIVÉS, lit `GITHUB_TOKEN` depuis l'environnement et
    l'injecte dans l'URL via le format `https://x-access-token:TOKEN@github.com/...`
    (méthode officielle GitHub, voir docs.github.com/en/get-started/git-basics/
    caching-your-github-credentials-in-git).

    ⚠️ Sécurité : ne JAMAIS pousser un GITHUB_TOKEN sur un Space public.
    Utiliser cette feature uniquement en local (`chainlit run app.py`) ou
    sur un Space privé.
    """
    clone_url = url
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and url.startswith("https://github.com/"):
        clone_url = url.replace(
            "https://github.com/", f"https://x-access-token:{token}@github.com/"
        )
        log.info(f"📥 Clone shallow de {url} (avec auth GITHUB_TOKEN)")
    else:
        log.info(f"📥 Clone shallow de {url}")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", clone_url, str(target)],
        check=True,
        capture_output=True,
        timeout=60,
    )


def _read_text_safe(path: Path, max_chars: int = 10_000) -> str:
    """Lit un fichier en gérant les erreurs (encoding, missing) silencieusement."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _extract_dep_names(repo_path: Path) -> str:
    """Concatène les noms de dépendances déclarées (TOML/requirements).

    On évite de matcher dans tout le fichier (sinon les commentaires comme
    'alternative à Gradio' déclenchent un faux positif). On extrait
    uniquement les noms officiels des dépendances déclarées.
    """
    chunks: list[str] = []

    # 1. pyproject.toml — section [project].dependencies + optional-dependencies
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            project = data.get("project", {})
            chunks.extend(project.get("dependencies", []))
            for group in project.get("optional-dependencies", {}).values():
                chunks.extend(group)
        except (tomllib.TOMLDecodeError, OSError):
            pass

    # 2. requirements.txt — une dep par ligne
    req = repo_path / "requirements.txt"
    if req.exists():
        chunks.extend(req.read_text(encoding="utf-8", errors="ignore").splitlines())

    return "\n".join(chunks)


def _detect_techs(repo_path: Path) -> list[str]:
    """Liste les technos détectées via patterns + fichiers présents."""
    found: set[str] = set()

    deps_text = _extract_dep_names(repo_path)

    # Match patterns regex sur les NOMS de deps (sans les commentaires)
    for tech, patterns in TECH_PATTERNS.items():
        for pattern, _file_key in patterns:
            if re.search(pattern, deps_text, re.IGNORECASE):
                found.add(tech)
                break

    # Fichiers/dossiers dont la simple présence suffit
    for tech, indicator in PRESENCE_INDICATORS.items():
        if (repo_path / indicator).exists():
            found.add(tech)

    return sorted(found)


def _extract_description(repo_path: Path) -> str:
    """Récupère la description du projet depuis README ou pyproject.toml."""
    # 1. Tenter le README — on prend les 2 premiers paragraphes
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        readme = repo_path / name
        if readme.exists():
            text = _read_text_safe(readme, max_chars=2000)
            # Strip header markdown et garde les premiers paragraphes substantiels
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            # On filtre les titres-only et badges
            useful = [p for p in paragraphs if len(p) > 50 and not p.startswith("#")]
            if useful:
                return "\n\n".join(useful[:2])[:1000]

    # 2. Fallback : description de pyproject.toml
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            return data.get("project", {}).get("description", "")
        except (tomllib.TOMLDecodeError, OSError):
            pass

    return ""


def _has_tests(repo_path: Path) -> bool:
    """Détecte si le projet a des tests automatisés."""
    if (repo_path / "tests").is_dir():
        return True
    if (repo_path / "test").is_dir():
        return True
    # Pattern test_*.py à la racine ou dans src/
    for parent in [repo_path, repo_path / "src"]:
        if parent.is_dir() and any(parent.glob("test_*.py")):
            return True
    return False


def _main_directories(repo_path: Path, limit: int = 8) -> list[str]:
    """Liste les dossiers de premier niveau (hors caches/git)."""
    skip = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", ".idea"}
    dirs = sorted(
        d.name
        for d in repo_path.iterdir()
        if d.is_dir() and d.name not in skip and not d.name.startswith(".")
    )
    return dirs[:limit]


def analyze_repo(url: str) -> RepoAnalysis:
    """Pipeline complet : clone → détecte → résume.

    Args:
        url: URL GitHub valide (https://github.com/org/repo).

    Returns:
        RepoAnalysis structurée. À passer ensuite à `to_natural_language()`
        pour obtenir une description compatible avec le pipeline RAG.

    Raises:
        ValueError: si l'URL n'est pas un repo GitHub valide.
        subprocess.CalledProcessError: si le clone échoue (repo privé, 404…).
    """
    match = GITHUB_URL_PATTERN.match(url)
    if not match:
        raise ValueError(f"URL GitHub invalide : {url}")

    org, repo = match.group(1), match.group(2)

    with tempfile.TemporaryDirectory(prefix="repo-analyzer-") as tmp:
        clone_path = Path(tmp) / repo
        _shallow_clone(url, clone_path)

        return RepoAnalysis(
            org=org,
            repo=repo,
            description=_extract_description(clone_path),
            techs=_detect_techs(clone_path),
            has_tests=_has_tests(clone_path),
            structure=_main_directories(clone_path),
        )
