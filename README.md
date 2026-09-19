# Christina Lab

**YouTube creator intelligence and content experimentation platform**

Christina Lab is a research and experimentation workspace for discovering unusually strong YouTube content, turning market signals into content ideas, and learning what actually works for a specific creator.

## Core loop

**Discover → Analyze → Save → Create Idea → Publish → Measure → Learn**

The product is designed around two connected systems:

- **Market Intelligence** — discover outliers, rising topics, fast-growing videos, repeatable hooks, title patterns, formats, and channel-level signals.
- **Christina Lab** — track ideas and published experiments, compare hypotheses with results, and build a creator-specific evidence base over time.

## Product goal

Answer one practical question:

> **What should I make a video about today, and why?**

The system should not encourage copying viral videos. It should help identify useful market signals, form a content hypothesis, test it, and learn from the result.

## Current status

### Phase 1 — UI/UX baseline ✅
The VibeFlow frontend and final light analytics theme are merged into `main` and treated as the Frontend V1 baseline.

### Phase 2 — Backend 🚧

**YouTube Milestones 1–5 implemented:**

- FastAPI backend
- real YouTube keyword search
- real video/channel public statistics
- views/hour
- 24h run rate (current pace extrapolated to 24 hours)
- public engagement rate
- views/subscriber ratio
- deeper recent-channel history scan with live/upcoming/unusable samples filtered out
- age-adjusted median channel velocity baseline from up to 12 usable comparison videos
- expected views at the candidate's current age
- real age-adjusted outlier multiplier
- explainable Opportunity Score v1.2 (0–100)
- score breakdown across outlier, velocity, engagement, views/subscriber, freshness, and baseline confidence
- guardrails for tiny channels, missing baselines, live content, and upcoming content
- gradual traction-confidence weighting instead of hard view-count score cliffs
- precise views/subscriber display for very small ratios
- existing Discover + Analyze UI connected to live results
- SQLite persistence for real video metric snapshots
- snapshot history for views / likes / comments over time
- true same-age historical baselines when at least 3 comparable observations exist
- provisional baseline clearly labeled and confidence-limited while history accumulates
- separate Short / regular Long-form / Livestream cohorts
- livestream replay detection via YouTube live metadata
- insufficient history is shown explicitly instead of inventing confidence
- real Dashboard backed by SQLite research history
- persisted Opportunity Score summaries
- actual measured growth leaders from 2+ snapshots
- real content-type dataset mix
- real Patterns page using persisted search topics, repeated title language, content cohorts, and measured growth
- Pattern Quality Pass: SEO/noise-cleaned title signals, useful hashtag compound normalization, and cross-channel repetition requirements
- growth distributions with median, top quartile, measured-history count, and positive-growth share
- clearer dataset labels distinguishing all observed videos from analyzed Discover candidates
- empty/pending states when the dataset is too small instead of fabricated pattern conclusions

**Next backend milestone:**

- add saved research persistence
- connect Ideas/Experiments to persisted research
- later: automated watchlist snapshot checks with quota-aware scheduling

Later work:

- saved research and ideas
- creator experiment tracking
- YouTube Analytics integration for owned-channel metrics

## Planned V1 workflow

1. Search a topic, keyword, or channel.
2. Retrieve recent YouTube videos and public metrics.
3. Calculate understandable signals such as:
   - video age
   - views/hour
   - 24h run rate
   - engagement rate
   - views/subscriber ratio
   - performance versus channel baseline
   - explainable Opportunity Score and guardrails
4. Identify promising outliers.
5. Save research.
6. Turn research into a content idea and hypothesis.
7. Track the published experiment.
8. Record what was learned.

## V1 success criteria

V1 is useful when a user can:

**Search YouTube → identify an outlier → understand why it was flagged → save it → turn it into an idea → track the experiment.**

## Repository policy

This repository is public for portfolio and development visibility. It currently has **no open-source license**. No permission is granted to reuse, redistribute, or commercially use the source code beyond rights provided by applicable law.

Never commit API keys, tokens, credentials, or real environment files.

See [docs/PRD.md](docs/PRD.md) for the full product requirements.

For local YouTube V1 setup, see [backend/README.md](backend/README.md).
