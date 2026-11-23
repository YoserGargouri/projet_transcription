# Plateforme AgentKit : API FastAPI + application web + moteur (STT, LLM, TTS), en une image.
#
#   docker compose up --build              # http://localhost:8000
#
# Les clés (LLM, ElevenLabs) ne sont JAMAIS dans l'image : elles viennent du fichier .env au
# lancement (docker-compose.yml). Données et caches de modèles : volume /data.

# ---------------------------------------------------------------- 1. interface web (Node)
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. moteur + API (Python)
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AGENTKIT_RUNTIME=/data/runtime \
    HF_HOME=/data/hf-cache \
    HF_HUB_DISABLE_TELEMETRY=1

# libgomp1 : calcul parallèle de faster-whisper / scikit-learn ; libportaudio2 : import de sounddevice
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libportaudio2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances d'abord (couche mise en cache tant que pyproject.toml ne change pas).
# PyTorch en version CPU : la version par défaut embarque CUDA (~2 Go inutiles ici).
COPY pyproject.toml README.md ./
RUN mkdir -p src/agentkit && touch src/agentkit/__init__.py \
 && pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -e ".[audio,ml,web]" pytest

# Code, packs de domaine, tests, interface construite
COPY src/ src/
COPY domains/ domains/
COPY tests/ tests/
COPY conftest.py .env.example ./
COPY --from=web /web/dist web/dist

# Facultatif : modèles téléchargés dès la construction (image plus lourde, premier appel immédiat)
#   docker compose build --build-arg PRELOAD_MODELS=1
ARG PRELOAD_MODELS=0
RUN if [ "$PRELOAD_MODELS" = "1" ]; then \
      python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" && \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"; \
    fi

# Utilisateur sans privilèges ; /data lui appartient (base, agendas, audios, caches)
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data/runtime /data/hf-cache \
 && chown -R app:app /data
USER app

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "agentkit.server", "--host", "0.0.0.0", "--port", "8000"]
