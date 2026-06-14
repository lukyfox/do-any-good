# Single image for both services. Default command runs the FastAPI backend;
# docker-compose runs the Gradio client from the same image with an overridden
# command. Secrets are provided at runtime (env), never baked into the image.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./backend/
COPY client/ ./client/

ENV DAG_DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 8000 7860

# Backend API by default; the client service overrides this command.
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
