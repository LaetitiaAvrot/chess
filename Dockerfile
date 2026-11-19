FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/games/stockfish /usr/local/bin/stockfish

WORKDIR /app
ENV IN_CONTAINER=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ scripts/
COPY Makefile .

CMD ["make", "help"]
