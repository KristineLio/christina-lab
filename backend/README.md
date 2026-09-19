# Christina Lab backend — YouTube V1

This milestone connects the existing **Discover** UI to real public YouTube data.

## What V1 does

```
Search term
  → FastAPI /api/discover
  → YouTube Data API v3
  → videos + channels + public statistics
  → views/day + views/hour + engagement + views/subscriber
  → existing Discover UI
```

Channel-baseline outlier scoring is intentionally **not** part of this milestone. The UI shows that as the next milestone instead of inventing a score.

## Local setup

From the repository root:

1. Create a local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Add your real YouTube Data API key to `.env`:

   ```env
   YOUTUBE_API_KEY=your_real_key_here
   ```

3. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install backend dependencies:

   ```powershell
   pip install -r backend/requirements.txt
   ```

5. Start FastAPI:

   ```powershell
   uvicorn backend.app.main:app --reload --port 8000
   ```

6. In a second terminal, serve the frontend on port 5500:

   ```powershell
   py -m http.server 5500
   ```

7. Open:

   ```
   http://localhost:5500
   ```

8. Go to **Discover** and search for `AI tools`.

## Useful checks

Health:

```
http://127.0.0.1:8000/api/health
```

Example API request:

```
http://127.0.0.1:8000/api/discover?q=AI%20tools
```

The real `.env` file is ignored by Git and must never be committed.
