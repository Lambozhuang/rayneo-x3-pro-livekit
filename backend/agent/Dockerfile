FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Mesa for render.py: a headless EGL context with software rasterisation
# (llvmpipe). No display, no GPU needed; a few thousand triangles at 15 fps
# is a small fraction of one core.
RUN apt-get update && apt-get install -y --no-install-recommends         libegl1 libgles2 libgl1 libgl1-mesa-dri libegl-mesa0 libgbm1     && rm -rf /var/lib/apt/lists/*
ENV EGL_PLATFORM=surfaceless MODEL_GL_BACKEND=egl

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src ./src
COPY guides ./guides

# Health check port of the agent framework; nothing else is exposed, and
# compose does not publish even this one.
EXPOSE 8081
CMD ["uv", "run", "--no-sync", "python", "src/agent.py", "start"]
