# Use officially supported Python image as base
FROM python:3.11-slim

# Set environment paths
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKSPACE_ROOT=/app

WORKDIR ${WORKSPACE_ROOT}

# Install essential dependencies for building Mangle or future integrations
RUN apt-get update && apt-get install -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the entire workspace root payload (backend, mangle_facts, standalone scripts)
# .dockerignore should be configured to drop heavy environments and raw datasets
COPY . ${WORKSPACE_ROOT}

# Switch working directory to where requirements are housed to install FastAPI dependencies
WORKDIR ${WORKSPACE_ROOT}/backend
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Google Mangle Linux Cross-Compilation Strategy ---
# IMPORTANT: The `./mg` local binary is an ARM64 Apple binary. It CANNOT run on standard Linux Cloud Run.
# In production, either replace this line with a WGET to a precompiled Linux binary release
# OR mount Bazel to compile the `mangle` engine directly inside the container from source!
# For now, we stub the pathway so execution fails over safely in python routers if it cannot find correct dependencies.
RUN echo "Mangle Linux stub deployed. Waiting for architectural binary." > /usr/local/bin/mg_linux_stub

# Run FastAPI Server on standard port 8000
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
