FROM python:3.12-slim

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY src/ src/

RUN uv venv --python 3.12 "${VIRTUAL_ENV}"
RUN uv pip install --python "${VIRTUAL_ENV}/bin/python" -e .

CMD ["uvicorn", "aetos.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
