# Christina Lab backend — YouTube Milestone 2

The Discover workflow now uses real public YouTube data and computes an explainable **channel outlier score**.

## Current flow

```
Search term
  → FastAPI /api/discover
  → YouTube Data API v3
  → candidate videos + channel public statistics
  → each channel's recent uploads playlist
  → recent upload view counts
  → median channel baseline
  → candidate views ÷ channel median
  → real Christina Lab outlier score
  → existing Discover UI
```

## Metrics

For every search result Christina Lab calculates:

- views/hour
- views/day
- public engagement rate = (likes + comments) / views
- views/subscriber ratio
- channel baseline
- outlier score

### Channel baseline

For each candidate video:

1. Fetch up to 12 recent public uploads from that channel.
2. Exclude the candidate itself from its baseline.
3. Prefer at least 3 recent uploads with the same coarse format:
   - `Short` = duration <= 3 minutes
   - `Long-form` = duration > 3 minutes
4. If fewer than 3 same-format uploads exist, fall back to all recent usable uploads.
5. Use the **median view count** as the channel baseline.
6. Calculate:

```
outlier = candidate current views / median recent channel views
```

Example:

```
Candidate current views: 12,000
Channel median baseline:  2,400
Outlier score:              5.0×
```

The score is derived by Christina Lab from public YouTube data. It is **not an official YouTube metric**.

If fewer than 3 usable recent uploads exist, no outlier score is shown instead of inventing a baseline.

## Quota-aware design

The implementation avoids running a costly YouTube search for every channel. It gets each channel's uploads playlist and then batches video-stat requests. This keeps baseline enrichment much cheaper than doing one `search.list` call per candidate channel.

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

3. Create a virtual environment:

   ```powershell
   py -m venv .venv
   ```

4. Install backend dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
   ```

5. Start FastAPI:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
   ```

6. In a second terminal, serve the frontend on port 5500 from the repository root:

   ```powershell
   py -m http.server 5500
   ```

7. Open the repo subfolder served by your current parent-directory setup if needed, for example:

   ```
   http://localhost:5500/christina-lab/
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
