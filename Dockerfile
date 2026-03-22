FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY src/ src/
ENV PYTHONPATH=/app/src

RUN uv pip install --system -e .

CMD ["uvicorn", "aetos.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
