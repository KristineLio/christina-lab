# Christina Lab — Product Requirements Document

## 1. Product summary

**Christina Lab** is a YouTube creator-intelligence and content-experimentation platform.

It helps a creator:

- discover unusually high-performing YouTube videos,
- understand why a video may be interesting,
- save market research,
- turn research into content hypotheses,
- publish experiments,
- compare the result with the original hypothesis,
- learn which topics, hooks, and formats work specifically for that creator.

The product is not intended to be a generic social-media dashboard, posting scheduler, or viral-video copier.

Its core loop is:

**Discover → Analyze → Save → Create Idea → Publish → Measure → Learn**

## 2. Main product question

The application should help answer:

> **What should I make a video about today, and why?**

## 3. Product model

Christina Lab contains two connected intelligence layers.

### 3.1 Market Intelligence

Tracks public YouTube content and surfaces:

- unusually strong-performing videos,
- fast-growing videos and channels,
- channel-level outliers,
- rising topics,
- repeated hook structures,
- repeated title patterns,
- promising formats,
- content opportunities worth testing.

### 3.2 Christina Lab

Tracks the creator's own experiments and results:

- content ideas,
- hypotheses,
- published videos,
- 24h / 48h / 7d performance,
- retention and CTR where available,
- engagement,
- subscriber gain,
- source research,
- GO / TEST / HOLD decisions,
- lessons and next experiments.

The product becomes more valuable as the creator's personal dataset grows.

## 4. Initial target user

Initial user: a solo creator building a YouTube channel while also building products in public.

Potential future users:

- solo creators,
- indie hackers,
- small businesses,
- marketers,
- founders,
- creators validating a niche.

## 5. Initial research categories

Start narrow rather than attempting to index every YouTube niche.

### Building in public
- apps
- AI tools
- coding
- indie hacking
- project development

### Trading / RiskDesk
- trading psychology
- signal tracking
- trade management
- beginner mistakes
- risk management
- copy-trading observations

### Creator journey
- growing from zero
- marketing experiments
- product-building challenges
- learning in public

## 6. Core V1 user flow

### Step 1 — Search
The user searches by:

- keyword,
- niche,
- topic,
- channel.

### Step 2 — Retrieve data
For each result, retrieve available public data such as:

- thumbnail,
- title,
- channel,
- publish timestamp,
- duration,
- views,
- likes,
- comments,
- channel subscriber count where available.

### Step 3 — Calculate research signals
Calculate understandable metrics such as:

- video age,
- views/hour,
- views/day,
- engagement rate,
- views/subscriber ratio,
- recent-channel baseline,
- outlier multiplier.

### Step 4 — Detect outliers
Compare a video with a channel's recent normal performance.

Primary explanation:

**Outlier multiplier = current video performance / recent channel baseline**

Examples:

- 1.2× — Normal
- 2.4× — Interesting
- 4.9× — Strong
- 11.3× — Extreme

The multiplier is a research signal, not a guarantee of future performance.

### Step 5 — Analyze
The user can open a detailed research view showing:

- performance summary,
- channel baseline,
- why the video was flagged,
- related opportunities,
- creator notes,
- content-analysis fields.

### Step 6 — Save
Interesting videos can be saved into research collections.

### Step 7 — Turn into idea
A saved video can become a content idea containing:

- working title,
- hook,
- topic,
- content type,
- unique angle,
- source videos,
- hypothesis,
- notes,
- pipeline status.

### Step 8 — Run experiment
Once published, the idea becomes an experiment.

### Step 9 — Measure
Track:

- 1h / 6h / 24h / 48h / 7d / 30d results,
- views,
- likes,
- comments,
- subscribers,
- retention,
- CTR where available.

### Step 10 — Learn
Record:

- GO,
- TEST,
- HOLD,
- what worked,
- what did not,
- what to test next.

## 7. V1 pages

### Dashboard
Daily summary of market and creator activity.

Core widgets:

- Videos Scanned
- Outliers Found
- Saved Research
- Active Experiments
- Today's Opportunities
- Fastest Growing
- Biggest Outliers
- Content Pipeline
- Recent Experiments

### Discover
Primary research workspace.

Capabilities:

- keyword/channel/topic search,
- time filters,
- Shorts vs long-form filtering,
- minimum views,
- channel-size filter,
- sorting by opportunity/outlier/views/velocity/engagement/newest,
- save,
- analyze,
- turn into idea.

### Video Analysis
Deep research page showing:

- video metadata,
- public performance,
- channel baseline,
- outlier multiplier,
- performance trajectory,
- why it was flagged,
- content-analysis fields,
- creator notes,
- related opportunities.

### Saved Research
Research library containing:

- saved videos,
- tags,
- topics,
- collections,
- notes,
- outlier data.

### Ideas
Kanban-style pipeline:

- Inbox
- Researching
- Ready
- Recorded
- Published
- Analyzing

### Christina Lab / Experiments
Experiment workspace showing:

- hypothesis,
- source research,
- published video,
- metrics,
- outcome,
- GO / TEST / HOLD decision,
- lessons,
- next experiment.

### My Videos
Owned-channel video library and performance history.

### Patterns
Repeated signals across market and personal data:

- rising topics,
- winning hook types,
- title patterns,
- format signals.

### Analytics
Aggregate creator experiment analysis:

- performance by topic,
- performance by hook,
- performance by format,
- subscriber gain,
- retention,
- publishing trends,
- market signal vs personal result.

### Watchlists
Track:

- channels,
- topics,
- recent outliers,
- momentum,
- last scan.

### Settings
Configuration for:

- YouTube Data API,
- creator analytics connection,
- research preferences,
- appearance,
- local data.

## 8. V1 technical scope

### Frontend
The approved Vibe Flow interface is the product/UI baseline.

Expected frontend architecture:

- reusable components,
- responsive layout,
- clear data interfaces,
- no secrets in client code.

### Backend
Preferred direction:

- Python
- FastAPI
- REST endpoints initially

### Database
Start simple:

- SQLite for local development,
- PostgreSQL when hosted.

### External APIs
Primary external source:

- YouTube Data API

Later:

- YouTube Analytics API for authenticated owned-channel data.

## 9. Initial backend modules

Suggested modules:

- youtube_service
- video_repository
- channel_repository
- research_repository
- idea_repository
- experiment_repository
- outlier_engine
- analytics_service

## 10. Initial analytics model

### Views velocity

`views_per_hour = views / video_age_hours`

`views_per_day = views / video_age_days`

### Engagement

Initial approximation:

`engagement_rate = (likes + comments) / views`

### Subscriber-normalized signal

`views_subscriber_ratio = views / channel_subscribers`

Use carefully when subscriber count is unavailable or hidden.

### Channel baseline

For a channel, retrieve a useful recent-video sample and calculate robust baseline statistics such as median recent views or median age-normalized velocity.

Prefer medians over simple averages to reduce distortion from previous viral outliers.

### Outlier score

Initial understandable form:

`outlier_multiplier = video_performance / channel_baseline`

The exact performance measure may evolve after testing.

## 11. Opportunity score

A separate opportunity score may later combine:

- outlier strength,
- velocity,
- engagement,
- recency.

If implemented, every component must remain explainable. Avoid an unexplained "AI score."

## 12. Data entities

### Video
- youtube_video_id
- title
- description
- thumbnail_url
- channel_id
- published_at
- duration
- views
- likes
- comments
- captured_at

### Channel
- youtube_channel_id
- name
- thumbnail_url
- subscribers
- video_count
- captured_at

### Research snapshot
- video_id
- views_per_hour
- views_per_day
- engagement_rate
- views_subscriber_ratio
- channel_baseline
- outlier_multiplier
- classification
- captured_at

### Saved research
- video_id
- collection
- tags
- notes
- saved_at

### Idea
- title
- hook
- topic
- content_type
- angle
- audience
- hypothesis
- notes
- status
- priority
- source_video_ids
- created_at

### Experiment
- idea_id
- youtube_video_id
- hypothesis
- published_at
- decision
- lessons
- next_test

### Experiment metrics
- experiment_id
- captured_at
- age_bucket
- views
- likes
- comments
- subscribers_gained
- retention
- ctr

## 13. V1 non-goals

Do not build yet:

- TikTok scraping,
- Instagram analytics,
- automatic posting,
- full AI script generation,
- large ML models,
- complex sentiment analysis,
- team accounts,
- payments,
- mobile native apps,
- browser extensions,
- massive competitor databases,
- real-time monitoring.

## 14. Security requirements

- Never commit API keys or credentials.
- Keep secrets in environment variables.
- Use `.env.example` only for placeholder variable names.
- Avoid exposing server-only credentials to browser code.
- Validate external inputs in the backend.
- Add rate limiting/caching as API usage grows.

## 15. Product-language principles

Prefer clear, explainable labels:

- Strong Outlier
- Channel Baseline
- Views / Day
- Why this was flagged
- Save Research
- Turn into Idea
- Run Experiment
- What did we learn?

Avoid vague "AI magic" language.

## 16. V1 definition of done

V1 is complete when the real application can:

1. search YouTube,
2. retrieve real videos,
3. calculate useful research signals,
4. identify an outlier,
5. explain why it was flagged,
6. save the research,
7. turn it into an idea,
8. create an experiment,
9. record the result.

The shortest successful loop is:

**Search YouTube → see real videos → identify an outlier → save it → turn it into an idea.**

## 17. Longer-term roadmap

### V2
- automated daily opportunity feed,
- channel watchlists,
- topic clustering,
- thumbnail-pattern analysis,
- assisted hook analysis.

### V3
- creator-specific recommendations,
- automatic owned-channel analytics import,
- experiment comparison,
- historical trend charts.

### V4
- cross-platform intelligence:
  - TikTok
  - Instagram
  - Reddit
  - Google Trends

### V5
A creator-intelligence agent capable of producing evidence-backed prompts such as:

> "Three formats are breaking out in your research set. Your own previous experiments suggest one of them performs above your normal retention. Here is the next hypothesis worth testing."

The system should always distinguish broad market signals from the creator's own evidence.
