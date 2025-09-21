FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for browsers
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    ca-certificates \
    xvfb \
    # Browser dependencies for Chromium
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy project files
COPY . .

# Install Python dependencies
RUN uv sync

# Install Playwright browsers
# Use a persistent path so runtime can discover browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN uv run playwright install --with-deps chromium
RUN ln -s /root/.cache/ms-playwright ${PLAYWRIGHT_BROWSERS_PATH} || true

# Force Chromium usage (arm64 safe)
ENV BROWSER_USE_BROWSER=chromium
ENV BROWSER_USE_PLAYWRIGHT_CHANNEL=chromium

# Set display environment variable
ENV DISPLAY=:99

# Create startup script that starts Xvfb and then the application
RUN echo '#!/bin/bash\n\
# Start Xvfb in background\n\
Xvfb :99 -screen 0 1024x768x24 -nolisten tcp -dpi 96 &\n\
# Wait a moment for Xvfb to start\n\
sleep 2\n\
# Run the application\n\
exec "$@"' > /app/start.sh && chmod +x /app/start.sh

# Run the official agent startup script via Xvfb starter
CMD ["/app/start.sh", "./run_agent.sh"]
