FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and pyproject
COPY backend/requirements.txt /app/backend/
COPY backend/pyproject.toml /app/backend/

# Install python dependencies
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy source packages
COPY backend /app/backend
COPY agents /app/agents
COPY tools /app/tools
COPY orchestration /app/orchestration
COPY database /app/database
COPY data /app/data

ENV PYTHONPATH="/app:/app/backend"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
