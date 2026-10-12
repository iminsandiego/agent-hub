FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock && pip install setuptools==84.0.0
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps --no-build-isolation . \
    && useradd --uid 10001 --create-home agenthub \
    && mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
ENV AGENT_HUB_DATA_DIR=/data
EXPOSE 8765
ENTRYPOINT ["agent-hub"]
CMD ["serve", "--server-config", "/data/server.json", "--host", "0.0.0.0"]
