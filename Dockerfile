FROM node:20-slim AS landing-build

WORKDIR /app/landing

COPY landing/package*.json ./
RUN npm ci --no-fund --no-audit

COPY landing/ ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=landing-build /app/landing/dist /app/landing/dist

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

RUN mkdir -p data

CMD ["python", "main.py"]
