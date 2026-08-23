# --- stage 1: build the frontend static bundle ---
FROM node:20-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- stage 2: backend runtime, serving the built frontend ---
FROM python:3.12-slim AS backend
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /frontend/dist ./frontend_dist

ENV FRONTEND_DIST_PATH=/app/frontend_dist
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
