FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY migrations ./migrations
COPY tests ./tests

EXPOSE 8000
CMD ["python", "-m", "dataforge", "serve"]
