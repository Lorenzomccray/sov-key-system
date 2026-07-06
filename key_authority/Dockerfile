FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY key_authority.py .
RUN mkdir -p /data
VOLUME /data
ENV PEPPER_FILE=/data/pepper.txt
ENV DB_FILE=/data/keys.db
EXPOSE 8001
CMD ["uvicorn", "key_authority:app", "--host", "0.0.0.0", "--port", "8001"]
