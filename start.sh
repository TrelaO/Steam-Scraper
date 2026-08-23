#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Starting Steam AI-ETL (first run can take a few minutes to build)..."
docker compose up -d --build

echo "Waiting for the app to respond on http://localhost:8000 ..."
ready=0
for _ in $(seq 1 90); do
  if curl -s -o /dev/null http://localhost:8000; then
    ready=1
    break
  fi
  sleep 2
done

if [ "$ready" -eq 0 ]; then
  echo "App did not respond in time - opening the page anyway."
  echo "If it does not load, run: docker compose logs"
fi

URL="http://localhost:8000"
if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
else
  echo "Open $URL in your browser."
fi
