FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

ADD . /app

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"
#ENV PYTHONPATH="./app"

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []
# linux locale
#RUN apt-get update
#RUN apt-get install -y locales
#RUN sed -i -e 's/# ru_RU.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen && \
#    locale-gen
#ENV LC_ALL ru_RU.UTF-8
#ENV LANG ru_RU.UTF-8
#ENV LANGUAGE ru_RU:ru

# Add the community repository for musl-locales

# Install musl-locales and set up Russian locale
#RUN apk add --no-cache musl-locales \
#    && echo "ru_RU.UTF-8 UTF-8" > /etc/locale.gen \
#    && locale-gen

# Set locale environment variables
#ENV LC_ALL=ru_RU.UTF-8
#ENV LANG=ru_RU.UTF-8
#ENV LANGUAGE=ru_RU:ru

CMD ["uv", "run", "main.py"]
#CMD ["sleep", "1000000"]
