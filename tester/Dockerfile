FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends nmap curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir requests==2.32.3 matplotlib==3.9.2
WORKDIR /tester
COPY scenario.py analyze.py ./
CMD ["sleep", "infinity"]
