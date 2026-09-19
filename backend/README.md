# Christina Lab backend — Milestone 4 snapshots

Christina Lab now persists real public YouTube observations in SQLite and can graduate from estimated age adjustment to **true same-age historical baselines** as the dataset grows.

## Current flow

```
Search YouTube
  → candidate + recent channel videos
  → classify content:
       Short
       Long-form
       Livestream / livestream replay
  → store public metric snapshot:
       views
       likes
       comments
       subscribers
       observed timestamp
       video age at observation
  → check stored history for same channel + same content type + similar age
  → if at least 3 historical videos have comparable-age snapshots:
       use median historical views
       calculate REAL same-age outlier
    otherwise:
       use provisional lifetime-velocity estimate
       visibly mark it as estimated
       limit its Opportunity Score contribution
```

## Snapshot persistence

The local default database is:

```
sqlite:///./christina_lab.sqlite3
```

The database file is ignored by Git.

Every time Christina Lab sees a candidate or recent channel comparison video, the backend records a snapshot at most once every 15 minutes per video.

A snapshot contains:

- video ID
- observation timestamp
- video age in hours at observation
- views
- likes
- comments
- subscriber count at observation

This means repeated research gradually creates actual growth history such as:

```
1.0h  → 1,100 views
6.1h  → 8,400 views
12.2h → 14,900 views
24.0h → 22,100 views
48.4h → 28,700 views
```

There is intentionally **no hidden background polling in this milestone**. A new snapshot is created when Christina Lab sees the video again through research/search. Automated watchlist polling can be added later after quota and scheduling rules are designed.

## True same-age baseline

For a candidate at a given age, Christina Lab looks for previous videos from:

- the same channel
- the same content class
- a similar age window

The age tolerance is deliberately tighter for young videos and wider for older videos.

Examples:

- ~1h candidate → historical observations roughly within ±1h
- ~6h candidate → roughly ±2h
- ~12h candidate → roughly ±3h
- ~24h candidate → roughly ±6h
- ~48h candidate → roughly ±12h

For each previous video, only the snapshot closest to the candidate's age is used.

If at least 3 comparable historical videos exist:

```
candidate: 8,400 views at ~6h

previous same-type videos near ~6h:
2,100
2,500
3,000
4,200
5,100

median historical baseline = 3,000

historical same-age outlier
= 8,400 / 3,000
= 2.8×
```

This is much stronger than dividing an older video's lifetime total by its current age.

## Provisional fallback

On a brand-new database, there will not yet be enough same-age historical snapshots.

Until enough observations accumulate, Christina Lab falls back to the previous age-adjusted lifetime-velocity estimate, but now:

- the UI labels it **Estimated / Provisional**
- the API returns `baselineMethod = median-age-adjusted-velocity`
- historical baselines return `baselineMethod = historical-snapshot-median`
- estimated outlier contribution is capped at 24/40 Opportunity points
- estimated baseline confidence is capped at 2/5

This prevents an extreme provisional ratio such as `353×` from being treated with the same confidence as a real historical same-age comparison.

## Content classification

YouTube candidates and comparison videos are classified into three cohorts:

- **Short** — non-livestream videos up to 3 minutes
- **Long-form** — regular non-livestream videos over 3 minutes
- **Livestream** — current streams, upcoming streams, and completed livestream replays

Completed broadcasts are detected from YouTube's `liveStreamingDetails`, even when `liveBroadcastContent` has returned to `none`.

Historical same-age baselines do **not** mix these cohorts. A livestream is compared with prior livestream observations, not ordinary long-form uploads.

## Opportunity Score v1.2

Opportunity Score keeps the same transparent components:

| Component | Max points |
| --- | ---: |
| Outlier | 40 |
| 24h run rate | 20 |
| Engagement | 15 |
| Views / subscriber | 10 |
| Freshness | 10 |
| Baseline confidence | 5 |

Milestone 4 changes the confidence logic:

- historical same-age snapshots can earn the full outlier and confidence contribution
- provisional lifetime-velocity baselines are deliberately capped until real history exists
- the existing traction-confidence multiplier, tiny-channel protections, missing-baseline protection, live penalty, and upcoming protection remain

## Snapshot API

Health now includes snapshot-store stats:

```
GET /api/health
```

Snapshot totals:

```
GET /api/snapshots/stats
```

History for a specific video:

```
GET /api/videos/{video_id}/snapshots
```

Example response:

```json
{
  "videoId": "abc123",
  "count": 2,
  "snapshots": [
    {
      "observedAt": "2026-09-19T17:00:00Z",
      "ageHours": 1.1,
      "views": 1100,
      "likes": 83,
      "comments": 12,
      "subscribers": 42000
    },
    {
      "observedAt": "2026-09-19T22:00:00Z",
      "ageHours": 6.1,
      "views": 8400,
      "likes": 510,
      "comments": 76,
      "subscribers": 42100
    }
  ]
}
```

## Local setup

Your existing setup still works.

`.env` should contain:

```env
YOUTUBE_API_KEY=your_real_key
DATABASE_URL=sqlite:///./christina_lab.sqlite3
```

Run the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

Run the frontend in a second terminal:

```powershell
py -m http.server 5500
```

Then use Discover normally. Re-running a search later will add new observations for videos Christina Lab sees again.

The real `.env` and local SQLite database must never be committed.


## Milestone 5 — real Dashboard and Patterns

Dashboard and Patterns no longer depend on the frontend's demo dataset.

New persisted derived research table:

```
video_analyses
```

Each fresh Discover search stores the latest candidate-level signals:

- search topic
- Opportunity Score
- outlier
- baseline + baseline method
- 24h run rate
- engagement
- views/subscriber
- analysis timestamp

The existing `videos` records also retain richer display metadata such as channel title and thumbnail.

### Dashboard API

```
GET /api/dashboard
```

Returns real persisted:

- videos tracked
- snapshots stored
- videos with multiple snapshots
- analyzed candidates
- search topics tracked
- strongest latest Opportunity Scores
- fastest **actual** growth measured between snapshots
- Short / Long-form / Livestream dataset mix
- data-maturity indicators

### Patterns API

```
GET /api/patterns
```

Returns real persisted:

- search-topic signals from Discover queries
- content-type medians
- repeated words and two-word phrases from tracked titles
- actual growth leaders from videos with 2+ snapshots

The title pattern layer is intentionally literal and transparent. It does not claim AI-generated hook categories that the database cannot support.

If the dataset is too small for a pattern, the API returns an empty collection and the UI displays a pending state rather than inventing results.

### Important migration behavior

Milestone 5 automatically upgrades an existing Milestone 4 SQLite database by adding display metadata columns and the `video_analyses` table. Existing snapshots are preserved.

Historical searches from before Milestone 5 did not store derived Opportunity analysis rows, so the Dashboard's Opportunity and search-topic sections begin filling after the next fresh Discover searches.


## Milestone 5.1 — Pattern Quality Pass

Patterns now favor useful, cross-channel evidence instead of raw keyword frequency.

### Cleaner title signals

The title extractor now:

- strips common YouTube/SEO noise such as `#viral`, `#trending`, `#shortsfeed`, `#ytshorts`, `#explore`, and similar platform tags
- filters broad one-word category terms such as `trading`, `trader`, `trade`, `crypto`, and `bitcoin`
- still allows those broad words inside useful phrases such as `copy trading` and `trading journal`
- normalizes useful concatenated hashtag/title compounds such as:
  - `copytrading` → `copy trading`
  - `tradingjournal` → `trading journal`
  - `aitools` → `ai tools`
  - `daytrading` → `day trading`
- keeps short meaningful tokens such as `AI`
- requires a title signal to appear across at least **two different channels**, not merely two videos from one prolific channel

Returned title signals now include:

- number of matching videos
- number of independent channels
- number of matching videos with an Opportunity Score
- average Opportunity Score when available

### Better growth distributions

Content-type patterns no longer show a lone `0/h actual` value with no context.

Each Short / Long-form / Livestream cohort now returns:

- total observed videos
- measured growth-history count
- median actual views/hour
- 75th percentile (top-quartile threshold) actual views/hour
- count of histories with positive growth
- positive-growth share

This makes a cohort with many flat observations understandable. For example:

```
Short
736 observed videos
318 measured growth histories
median actual growth: 0/h
top quartile: 420/h
positive growth: 41%
```

The median can truthfully remain zero without implying that the growth system is broken.

### Clearer dataset language

The UI now distinguishes:

- **Public Videos Observed** — candidates plus channel-history videos collected for baselines
- **Metric Snapshots** — timestamped public observations
- **Measured Growth Histories** — videos with at least two snapshots
- **Analyzed Search Results** — Discover candidates with persisted derived scores

Search Topic Signals also explicitly encourages multiple distinct Discover queries because cross-topic comparisons are not meaningful when only one search topic has been persisted.


## Milestone 5.1.1 — Title Signal Specificity

Repeated Title Signals now prioritize useful creative patterns over frequent generic language.

Additional cleanup:

- remove ordinary function/common words such as `for`, `the`, `how`, `new`, and `real`
- suppress common location noise such as `India`, `Dubai`, `London`, `USA`, `UK`, and `Singapore`
- suppress broad single words such as `gold`, `strategy`, `setup`, `motivation`, `day`, and `stockmarket`
- still allow those domain words inside meaningful phrases such as `gold strategy`, `trading setup`, `day trading`, `copy trading`, and `trading journal`
- normalize `stockmarket` into `stock market` before filtering
- rank multi-word phrases ahead of single-word signals
- label returned signals as either `phrase` or `specific-word`

The goal is for the page to favor patterns closer to:

```
copy trading
trading journal
beginner mistakes
AI tools
gold strategy
```

rather than raw frequency terms such as `for`, `the`, `day`, `gold`, or `trader`.


## Milestone 5.1.2 — Phrase quality cleanup

A final deterministic phrase cleanup removes awkward repeated bigrams without introducing hidden AI semantics.

Examples:

- `trading forex` is normalized to `forex trading`
- `action trading`, `trading motivation`, `motivation trading`, `trading like`, and `funny comedy` are suppressed
- filler singletons such as `action`, `funny`, `comedy`, and `like` are also prevented from surfacing by themselves
- useful phrases such as `price action`, `trading setup`, `day trading`, `copy trading`, and `trading journal` remain eligible

The goal is to stop hand-tuning after obvious cleanup and let broader datasets from different search topics determine what patterns are actually useful.
