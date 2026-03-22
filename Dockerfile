FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system -e .

COPY src/ src/

CMD ["uvicorn", "aetos.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
