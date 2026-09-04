FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src ./src

# Health check port of the agent framework; nothing else is exposed, and
# compose does not publish even this one.
EXPOSE 8081
CMD ["uv", "run", "--no-sync", "python", "src/agent.py", "start"]
