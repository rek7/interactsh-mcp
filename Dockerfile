# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip build \
 && python -m build --wheel --outdir /dist


FROM python:3.12-slim
LABEL org.opencontainers.image.title="interactsh-mcp" \
      org.opencontainers.image.description="MCP server for ProjectDiscovery's Interactsh" \
      org.opencontainers.image.licenses="MIT"

# Run as a non-root user — the server only needs outbound HTTPS to the
# interactsh host, so no extra privileges required.
RUN useradd --create-home --uid 10001 app
WORKDIR /home/app

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
 && rm -f /tmp/*.whl

USER app

# MCP runs over stdio — Claude Code, Codex CLI, etc. spawn the container and
# talk to it on stdin/stdout. Override INTERACTSH_SERVER / INTERACTSH_TOKEN
# at run time to point at a self-hosted server.
ENV INTERACTSH_LOG_LEVEL=WARNING

ENTRYPOINT ["interactsh-mcp"]
