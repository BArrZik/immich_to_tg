# ==========================================
# Stage 1: Builder
# ==========================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libheif-dev \
    libde265-dev \
    pkg-config \
    python3-dev \
    gcc \
    musl-dev \
    && rm -rf /var/lib/apt/lists/*

# ⚠️ pyheif FIX: Explicitly set flags for C extensions
ENV CFLAGS="-I/usr/include/libheif"
ENV LDFLAGS="-lheif"

# 1. Install dependencies only (no project files yet)
# This RUN command uses mounts to read pyproject.toml and uv.lock
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# 2. Add the source code to the container
ADD . /app

# 3. Install the project itself (the source code is now present)
# This uses the previously installed dependencies.
RUN uv sync --frozen --no-dev

# ==========================================
# Stage 2: Final / Runtime
# Minimal image containing only the app and runtime libraries
# ==========================================
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install ONLY runtime libraries
# - libpq5: Runtime for psycopg2
# - libheif1, libde265-0: Runtime for pyheif
RUN apt-get update && apt-get install -y \
    libpq5 \
    libheif1 \
    libde265-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the environment from the builder stage
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# Add the virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Setup Locale (Optional but recommended for image processing/filenames)
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

CMD ["python", "main.py"]