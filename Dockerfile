# Ассистент поддержки: приложение + MCP-сервер в одном образе.
# MCP-серверу не нужны torch и модель эмбеддингов, но общий образ
# проще в сопровождении; при желании вынесите его в отдельный Dockerfile.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .

# torch только CPU-сборкой — GPU на VPS не нужен
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

# Предзагрузка модели эмбеддингов (~2,2 ГБ) в образ, чтобы первый
# запуск не ждал скачивания. Альтернатива: убрать этот шаг — модель
# скачается при первом запуске контейнера.
# Если huggingface.co недоступен с вашего VPS, раскомментируйте зеркало:
# ENV HF_ENDPOINT=https://hf-mirror.com
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('intfloat/multilingual-e5-large', device='cpu')"

COPY . .

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8550 \
    MCP_URL=http://mcp-server:8001/mcp \
    STORAGE_DIR=/data

EXPOSE 8550 8001

CMD ["python", "main.py"]
