FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.3 gunicorn==22.0.0 requests==2.32.3 psycopg2-binary==2.9.9
COPY app.py .
# Pocos hilos a proposito: facilita demostrar el agotamiento del pool.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:5000", "app:app"]
