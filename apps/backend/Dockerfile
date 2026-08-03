FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev

COPY src ./src

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "diploma_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
