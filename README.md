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

### Phase 1 — UI/UX baseline
The frontend prototype has been designed in Vibe Flow and will be imported into this repository as the visual/product baseline.

### Phase 2 — Backend
Planned backend work:

- YouTube Data API integration
- video and channel data ingestion
- outlier/velocity analytics
- persistence layer
- saved research and ideas
- creator experiment tracking
- YouTube Analytics integration for owned-channel metrics

## Planned V1 workflow

1. Search a topic, keyword, or channel.
2. Retrieve recent YouTube videos and public metrics.
3. Calculate understandable signals such as:
   - video age
   - views/hour
   - views/day
   - engagement rate
   - views/subscriber ratio
   - performance versus channel baseline
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
