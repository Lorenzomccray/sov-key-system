FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir streamlit requests pandas plotly
COPY dashboard.py .
RUN mkdir -p /root/.streamlit
RUN echo "[server]\nheadless = true\nport = 8501\n" > /root/.streamlit/config.toml
EXPOSE 8501
ENTRYPOINT ["streamlit", "run", "dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
