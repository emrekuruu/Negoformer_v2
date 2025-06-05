# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    bash \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files flat from negolog
COPY . .

# Copy and fix execution script
COPY run_pipeline.sh /app/run_pipeline.sh
RUN dos2unix /app/run_pipeline.sh && chmod +x /app/run_pipeline.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the pipeline
ENTRYPOINT ["/app/run_pipeline.sh"]
