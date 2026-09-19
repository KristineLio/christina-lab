# Christina Lab backend — Age-adjusted YouTube outliers

The Discover workflow uses real public YouTube data, a deeper cleaned channel-history sample, and an explainable **age-adjusted channel outlier score**.

## Current flow

```
Search term
  → FastAPI /api/discover
  → YouTube Data API v3
  → candidate videos + channel public statistics
  → each channel's recent uploads
  → calculate average view velocity for recent uploads
  → median channel view velocity
  → estimate expected views at the candidate's current age
  → candidate velocity ÷ channel median velocity
  → age-adjusted outlier score
  → Discover + Analyze UI
```

## Why the baseline is age-adjusted

A brand-new video should not be compared directly with the lifetime/current totals of older videos.

Bad comparison:

```
new video: 500 views after 5 hours
older channel median: 5,000 total views
500 / 5,000 = 0.1x
```

That penalizes the new video simply because it has had less time to collect views.

The current Christina Lab baseline instead compares **average view velocity**:

```
candidate velocity
= candidate views / candidate age in hours

channel baseline velocity
= median(recent video views / recent video age in hours)

outlier
= candidate velocity / channel baseline velocity
```

Then the median channel velocity is projected to the candidate's age:

```
expected views at this age
= channel baseline velocity × candidate age
```

Example:

```
Candidate:
500 views after 5 hours
= 100 views/hour

Recent channel videos:
2,400 views after 24h  = 100/hour
4,800 views after 48h  = 100/hour
7,200 views after 72h  = 100/hour

Median channel velocity = 100/hour
Expected at 5h = 500 views

Age-adjusted outlier = 1.0x
```

## Important limitation

YouTube's public Data API gives the **current cumulative view count** of a video. It does not give us the exact historical view count that an older video had at, for example, exactly 5 or 6 hours after publishing.

So this age-adjusted score is an approximation based on each recent video's current average views/hour.

That is still fairer for new videos than comparing against older lifetime totals, but it is not a true same-age historical baseline.

A later persistence milestone can store Christina Lab's own periodic snapshots. Once enough snapshots exist, the system can compare:

```
candidate at 6h
vs
historical channel videos at 6h
```

which is the stronger long-term method.

## Baseline rules

For each candidate video:

1. Scan up to 30 recent public uploads from the channel.
2. Exclude the candidate itself.
3. Exclude live and upcoming videos, zero-view items, and samples missing usable publish timing.
4. Prefer at least 3 recent uploads with the same coarse format:
   - `Short` = duration <= 3 minutes
   - `Long-form` = duration > 3 minutes
5. If fewer than 3 same-format uploads exist, fall back to all recent usable uploads.
6. Use up to the 12 most recent usable comparison videos.
7. Calculate the median average views/hour.
8. Project that velocity to the candidate's current age.
9. Compare candidate velocity with that median velocity.

If fewer than 3 usable recent uploads exist, Christina Lab shows no outlier score instead of inventing one.

## Other live metrics

For each search result Christina Lab also calculates:

- views/hour
- 24h run rate = current average views/hour × 24 (an extrapolated pace, not actual 24-hour views)
- public engagement rate = (likes + comments) / views
- views/subscriber ratio
- expected views at current age
- age-adjusted outlier score

## Local setup

The existing local setup is unchanged.

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

Frontend, in a second terminal:

```powershell
py -m http.server 5500
```

Then open the Christina Lab frontend and search in **Discover**.

The real `.env` file remains ignored by Git and must never be committed.
