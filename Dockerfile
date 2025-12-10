# Stage 1: Build Frontend
FROM node:20-alpine as frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Build Backend & Serve
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install system dependencies if needed
# RUN apt-get update && apt-get install -y gcc

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/ ./backend/

# Copy Frontend Build
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Expose Port
EXPOSE 8000

# Run Application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
