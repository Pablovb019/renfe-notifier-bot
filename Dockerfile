FROM python:3.12-slim

# Dependencias del sistema para Selenium + Firefox y zona horaria
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    wget \
    ca-certificates \
    xvfb \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Madrid
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Instalar geckodriver (driver de Firefox)
ARG GECKODRIVER_VERSION=0.37.1
RUN wget -q "https://github.com/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz" \
    && tar -xzf "geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz" -C /usr/local/bin \
    && rm "geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz"

WORKDIR /app

# 1. Copiar primero solo los requerimientos para cachear la capa de pip
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# 2. Copiar el código fuente AL FINAL (los cambios en código no invalidan las capas anteriores)
COPY . /app

CMD ["python", "python/renfebot.py", "--database", "/data/renfebot.db"]
