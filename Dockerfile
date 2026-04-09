# SQL/Data Cleaning Sandbox  Dockerfile for Hugging Face Spaces

# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install required system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app/

# Install python dependencies directly bypassing complex managers to ensure maximum Hugging Face compatibility
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir uvicorn openenv-core[core]>=0.2.2 requests>=2.31.0 openai>=1.0.0 groq>=0.4.0 python-dotenv

# OpenEnv needs the workspace in PYTHONPATH
ENV PYTHONPATH="/app"
# Default fallback task
ENV TASK_ID="easy"

# Hugging Face Spaces exposes port 7860
EXPOSE 7860
ENV ENABLE_WEB_INTERFACE=true
# Command to run the OpenEnv Server directly
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860"]