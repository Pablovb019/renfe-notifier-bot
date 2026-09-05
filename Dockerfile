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
COPY . /app

# (Recomendado) actualizar tooling base
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Dependencias Python actualizadas
RUN pip install --no-cache-dir --upgrade \
    "python-telegram-bot[job-queue]" \
    selenium \
    pyvirtualdisplay \
    emoji \
    json5 \
    urllib3 \
    requests \
    certifi

CMD ["python", "python/renfebot.py", "--database", "/data/renfebot.db"]
