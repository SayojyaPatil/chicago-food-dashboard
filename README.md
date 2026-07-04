# Chicago Food Safety Dashboard

End-to-end BI application: Python ETL pipeline → FastAPI REST layer → React/Recharts dashboard.

Data source: [Chicago Dept of Public Health — Food Inspections](https://data.cityofchicago.org/resource/4ijn-s7e5.json) (live, 200k+ records)

---

## Stack

| Layer     | Tech                                      |
|-----------|-------------------------------------------|
| ETL       | Python, Requests, psycopg2                |
| Database  | PostgreSQL                                |
| Backend   | FastAPI, asyncpg, databases               |
| Frontend  | React 18, Recharts, Vite                  |
| Deploy    | Railway (backend + DB), Vercel (frontend) |

---

## Local Setup

### 1. PostgreSQL

Create the database:
```bash
psql -U postgres -c "CREATE DATABASE food_inspections;"
```

### 2. Environment Variables

```bash
cp .env.example .env
# Fill in DB_PASSWORD and DATABASE_URL
```

### 3. Run ETL

```bash
cd etl
pip install requests psycopg2-binary python-dotenv
python etl.py
# Fetches ~50k records from Chicago Data Portal and loads into PostgreSQL
```

### 4. Run Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### 5. Run Frontend

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:5173
```

---

## API Endpoints

| Endpoint                       | Description                               |
|--------------------------------|-------------------------------------------|
| `GET /health`                  | Health check                              |
| `GET /metrics/kpi-summary`     | Total inspections, pass rate, fail counts |
| `GET /metrics/pass-fail-trend` | Monthly pass/fail for last 24 months      |
| `GET /metrics/risk-distribution` | Fail rate by risk level (High/Med/Low)  |
| `GET /metrics/top-facility-types` | Top 10 facility types by volume        |
| `GET /metrics/zip-fail-rates`  | Top 15 zip codes by failure count         |

---

## Deploy to Railway + Vercel

### Backend + DB (Railway)

1. Push repo to GitHub
2. New Railway project → Add PostgreSQL service
3. Add backend service → set root directory to `backend/`
4. Set `DATABASE_URL` env var from Railway PostgreSQL service
5. Run ETL once against Railway DB: set `DATABASE_URL` in `.env` and run `python etl.py`
6. Railway auto-detects `requirements.txt` and runs `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Frontend (Vercel)

1. New Vercel project → root directory `frontend/`
2. Set env var: `VITE_API_URL=https://your-railway-backend-url.railway.app`
3. Deploy — Vercel handles Vite build automatically

---

## Dashboard Features

- KPI summary row: total inspections, pass rate, failures, high-risk fail rate, zip codes covered
- Monthly pass/fail trend line chart (24 months)
- Failure rate by risk level bar chart
- Top 10 facility types horizontal bar chart
- Top 15 zip codes by failure count
