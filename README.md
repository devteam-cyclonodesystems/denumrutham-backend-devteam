# Denumrutham Temple Management System (TMS) — Backend API

This repository houses the Python-based FastAPI backend engine for the **Denumrutham** SaaS Temple Management platform.

## Features & Technologies
- **Framework**: FastAPI
- **Database ORM**: SQLAlchemy (Async)
- **Database Migrations**: Alembic
- **Deployment Platform**: Railway (configured with `railway.json` / `Procfile`)
- **Database Engine**: Neon PostgreSQL (Serverless)

---

## 🛠️ Local Development & Setup

### Prerequisites
- Python 3.10+
- PostgreSQL or Neon Postgres database
- Redis (optional, for rate-limiting cache)

### 1. Install Dependencies
Set up a virtual environment and install the required modules:
```bash
python -m venv .venv
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in the correct configuration values:
- `DATABASE_URL`: Your local database URL or Neon PostgreSQL URL. Note that for async operations, the `postgresql+asyncpg://` protocol is used.
- `SECRET_KEY`: Random string for general encryption.
- `JWT_SECRET`: Random string for authentication tokens.
- `PORT`: Port to run the FastAPI app (default: `8000`).
- `CORS_ALLOWED_ORIGINS`: Origins allowed to communicate with the API (e.g. `http://localhost:5173`).
- `REDIS_URL`: Connection string for Redis cache.
- `ENVIRONMENT`: `development` or `production`.

### 3. Run Database Migrations
Deploy the database schema using Alembic:
```bash
alembic upgrade head
```

### 4. Start Server
Run the FastAPI development server:
```bash
uvicorn app.main:app --reload --port 8000
```
API docs will be available at `http://localhost:8000/docs`.

---

## 🐘 Neon PostgreSQL Setup

Neon is a serverless PostgreSQL service. To connect to Neon:
1. Create a project at [Neon Console](https://neon.tech).
2. Create a database (e.g., `tms_postgres`).
3. Retrieve your connection string from Neon. It will look like this:
   `postgresql://<user>:<password>@<neon-host>/tms_postgres?sslmode=require`
4. For FastAPI async operations, prefix the protocol with `+asyncpg` in your `.env` file:
   `DATABASE_URL=postgresql+asyncpg://<user>:<password>@<neon-host>/tms_postgres?sslmode=require`

---

## 🚀 Railway Deployment

The backend is configured for deployment on **Railway** using the `Dockerfile`, `Procfile`, and `railway.json` settings.

### Deployment Guide
1. Log in to [Railway](https://railway.app).
2. Click **New Project** → **Deploy from GitHub repo** and select `denumrutham-backend`.
3. Set the Environment Variables inside the Railway dashboard (see list below).
4. Railway will automatically build and launch the application using the configuration files.

### Required Environment Variables on Railway
Configure these variables in the **Variables** tab of your service:
- `DATABASE_URL`: Your production Neon Postgres async URL (with `postgresql+asyncpg://`).
- `SECRET_KEY`: A secure random cryptographic key.
- `JWT_SECRET`: A secure random key specifically for JWT signatures.
- `ENVIRONMENT`: Set to `production`.
- `LOG_LEVEL`: Set to `info` or `warning`.
- `PORT`: `${{PORT}}` (automatically assigned by Railway).
- `CORS_ALLOWED_ORIGINS`: Comma-separated list of allowed domains (e.g., `https://your-app.vercel.app`).
