# ── Base image: Playwright ships its own Chromium ─────────────────────────────
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN playwright install chromium --with-deps

# Copy application source
COPY bot/ ./bot/

# Default: run the checker
CMD ["python", "-m", "bot.checker"]
