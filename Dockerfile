# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (needed for some pandas/numpy builds)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Set environment variable for log output
ENV PYTHONUNBUFFERED=1

# Expose the FastAPI control plane
EXPOSE 8000

# Create a data directory for CSVs or local storage (if needed)
RUN mkdir -p data

# Execute the bot
CMD ["python", "main.py"]
