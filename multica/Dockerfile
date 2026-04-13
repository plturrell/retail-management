FROM python:3.11-slim

WORKDIR /app

# Install OS dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Multica agent codebase
COPY . .

# Expose the API port
EXPOSE 8000

# Start the FastAPI server on port 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
