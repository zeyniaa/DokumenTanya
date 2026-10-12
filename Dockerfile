FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY backend ./backend
ARG INSTALL_AI=false
RUN if [ "$INSTALL_AI" = "true" ]; then uv sync --frozen --no-dev --extra ai --extra ocr; else uv sync --frozen --no-dev --extra ocr; fi
COPY frontend ./frontend
COPY examples ./examples
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data /app/model-cache && chown -R appuser:appuser /app
ENV PATH="/app/.venv/bin:$PATH" DATA_DIR=/app/data HF_HOME=/app/model-cache PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
