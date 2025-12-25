# Lightweight Dockerfile for running pretix-race in headless mode
# No browser needed - just monitors and outputs cookies/webhook
#
# Build:
#   docker build -t pretix-race .
#
# Run:
#   docker run --rm pretix-race \
#     --url https://tickets.example.com \
#     --event myevent \
#     --headless \
#     --webhook https://your-server.com/notify

FROM python:3.12-slim

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files first (for caching)
COPY pyproject.toml uv.lock ./

# Install dependencies (skip playwright in headless-only image)
RUN uv sync --frozen --no-dev

# Copy source code
COPY src/ src/

# Create directory for response logs
RUN mkdir -p live-responses

# Default to headless mode
ENTRYPOINT ["uv", "run", "pretix-race", "--headless"]

# Show help by default
CMD ["--help"]
