# AgentCore Runtime expects an ARM64 image listening on 0.0.0.0:8000/mcp.
# Build with: docker buildx build --platform linux/arm64 -t macro-desk .
FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY macro_desk ./macro_desk

ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
USER nobody
CMD ["python", "-m", "macro_desk.server"]
