# NEA AI Agents — Engineer Onboarding Guide

Welcome to the NEA AI Agents codebase. This guide will help you understand how everything works, what you can modify, and where to look when things need to change.

---

## Table of Contents

1. [What This System Does](#what-this-system-does)
2. [The Three Agents at a Glance](#the-three-agents-at-a-glance)
3. [How Data Flows Through the System](#how-data-flows-through-the-system)
4. [Deep Dive: Meeting Briefing Agent](#deep-dive-meeting-briefing-agent)
5. [Deep Dive: News Aggregator Agent](#deep-dive-news-aggregator-agent)
6. [Deep Dive: Outreach Agent](#deep-dive-outreach-agent)
7. [The Data Layer](#the-data-layer)
8. [External API Integrations](#external-api-integrations)
9. [Customization Points](#customization-points)
10. [Current Capabilities & Limitations](#current-capabilities--limitations)
11. [Future Improvement Areas](#future-improvement-areas)
12. [Common Tasks & Recipes](#common-tasks--recipes)

---

## What This System Does

NEA AI Agents automates three key VC workflows:

| Agent | What it does | Time saved |
|-------|-------------|------------|
| **Meeting Briefing** | Generates comprehensive company research docs before meetings | 2-4 hours → 2 minutes |
| **News Aggregator** | Tracks portfolio + competitors for funding, hires, launches | Manual scanning → Automated alerts |
| **Outreach** | Creates personalized cold emails using investor voice profiles | 30 min/email → 30 seconds |

All three agents share the same data infrastructure, so company data fetched for one agent is available to others.

---

## The Three Agents at a Glance

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│   MEETING BRIEFING          NEWS AGGREGATOR           OUTREACH         │
│   ─────────────────         ──────────────────        ────────         │
│                                                                        │
│   Input: Company URL        Input: Watchlist          Input: Company   │
│                                    (portfolio +              + Investor│
│                                     competitors)             Profile   │
│                                                                        │
│   Output: Markdown          Output: Signal alerts     Output: Email or │
│           briefing with             + weekly digest           LinkedIn │
│           citations                                           message  │
│                                                                        │
│   LLM: Claude Sonnet 4.6    LLM: None (rule-based)   LLM: Claude      │
│                                                            Sonnet 4.5  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## How Data Flows Through the System

### The Shared Data Pipeline

All agents use `tools/company_tools.py` as the central data ingestion layer:

```
                              ┌─────────────────┐
                              │  company_tools  │
                              │    .py          │
                              └────────┬────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
┌───────────────┐            ┌─────────────────┐            ┌─────────────────┐
│   Harmonic    │            │ Parallel Search │            │     Swarm       │
│  (companies,  │            │    (news)       │            │   (founders)    │
│   founders,   │            │                 │            │                 │
│   metrics)    │            │                 │            │                 │
└───────┬───────┘            └────────┬────────┘            └────────┬────────┘
        │                             │                              │
        └─────────────────────────────┼──────────────────────────────┘
                                      │
                                      ▼
                           ┌──────────────────┐
                           │   SQLite + Supabase │
                           │   (local + cloud)   │
                           └──────────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┐
                │                     │                     │
                ▼                     ▼                     ▼
        ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
        │   Meeting     │    │     News      │    │   Outreach    │
        │   Briefing    │    │  Aggregator   │    │    Agent      │
        └───────────────┘    └───────────────┘    └───────────────┘
```

### Key Data Structures

All data is bundled into a `CompanyBundle` (defined in `core/database.py`):

```python
@dataclass
class CompanyBundle:
    company_core: Optional[CompanyCore]   # Name, funding, HQ, products
    founders: list[Founder]               # Names, titles, LinkedIn, backgrounds
    key_signals: list[KeySignal]          # Funding, hiring, product signals
    news: list[NewsArticle]               # Recent news with sentiment
```

---

## Deep Dive: Meeting Briefing Agent

**Location:** `agents/meeting_briefing/`

### Architecture

The agent uses **LangGraph** for workflow orchestration with parallel execution:

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           │
                           ▼
                ┌──────────────────┐
                │ validate_company │  ← Looks up company in Harmonic
                └────────┬─────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│retrieve_profile│ │ retrieve_news │ │retrieve_signals│  ← PARALLEL
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
              ┌────────────────────┐
              │ synthesize_briefing │  ← Claude LLM generates final output
              └─────────┬──────────┘
                        │
                        ▼
                    ┌───────┐
                    │  END  │
                    └───────┘
```

### Key Files

| File | Purpose | When to modify |
|------|---------|----------------|
| `agent.py` | Main workflow, state machine, CLI | Adding new retrieval sources, changing output format |
| `harmonic_source.py` | Harmonic API data source | Changing how company data is fetched |

### The DataSource Protocol

The agent uses a **Protocol pattern** for data sources, making it easy to swap implementations:

```python
# In agent.py
class DataSource(Protocol):
    def get_company_profile(self, url: str) -> RetrievalResult: ...
    def get_recent_news(self, url: str, days: int) -> RetrievalResult: ...
    def get_key_signals(self, url: str) -> RetrievalResult: ...
    def list_companies(self) -> list[str]: ...
```

**To add a new data source:**
1. Create a class implementing these 4 methods
2. Pass it to `MeetingBriefingAgent(data_source=YourSource())`

### Output Structure

The briefing is structured as markdown with these sections (defined in the system prompt at line ~897):

1. **TL;DR** — 2-3 sentences
2. **Why This Meeting Matters** — Investment-relevant bullets with citations
3. **Company Snapshot** — Table format
4. **Founders** — Names, titles, backgrounds
5. **Key Signals** — Recent events with sources
6. **In the News** — Article summaries
7. **Meeting Prep** — Questions and next steps

### Customization Points

| What | Where | How |
|------|-------|-----|
| Change LLM model | Line 99 | `DEFAULT_LLM_MODEL = "claude-sonnet-4-6"` |
| Change output format | Lines 897-977 | Edit the system prompt |
| Add new retrieval source | Lines 601-648 | Extend `CompositeDataSource` |
| Change news lookback | Line 98 | `DEFAULT_NEWS_DAYS = 30` |

---

## Deep Dive: News Aggregator Agent

**Location:** `agents/news_aggregator/`

### Architecture

Unlike the other agents, this one is **rule-based** (no LLM for signal detection):

```
┌──────────────────────────────────────────────────────────────────────┐
│                         WATCHLIST                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │
│  │  Portfolio  │  │ Competitors │  │ Competitors │  ...              │
│  │  (Stripe)   │  │  (Adyen)    │  │  (Block)    │                   │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                   │
└─────────┼────────────────┼────────────────┼──────────────────────────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │    Signal Detector    │
               │    (detector.py)      │
               └───────────┬───────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Harmonic    │  │Parallel Search│  │   Keyword     │
│   (metrics)   │  │    (news)     │  │Classification │
│               │  │               │  │               │
│ • Headcount Δ │  │ • Articles    │  │ • funding     │
│ • Traffic Δ   │  │ • Sentiment   │  │ • acquisition │
│               │  │               │  │ • team_change │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │   Relevance Scoring   │
               │   + Deduplication     │
               └───────────┬───────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │   Supabase Storage    │
               │   (company_signals)   │
               └───────────────────────┘
```

### Key Files

| File | Purpose | When to modify |
|------|---------|----------------|
| `agent.py` | CLI, noise filtering patterns | Adding companies, changing filters |
| `detector.py` | Signal detection logic | Adding signal types, changing classification |
| `database.py` | Supabase storage | Schema changes |
| `investor_digest.py` | Weekly digest generation | Changing digest format |

### Signal Types

Signals are classified by keywords in `detector.py`:

| Signal Type | Keywords | Source |
|-------------|----------|--------|
| `funding` | raise, series, seed, funding, round | News |
| `acquisition` | acquire, merger, m&a, bought | News |
| `team_change` | ceo, cto, hire, join, depart | News |
| `product_launch` | launch, release, announce, unveil | News |
| `partnership` | partner, collaborate, integrate | News |
| `hiring_expansion` | headcount change > 10% | Harmonic |
| `web_traffic` | traffic change > 20% | Harmonic |

### Noise Filtering

The agent filters out false positives using regex patterns (lines 56-104 in `agent.py`):

```python
NOISE_PATTERNS = [
    r'wikipedia\.org',
    r'list of.*companies',
    r'press release',
    # ... many more
]
```

**To add a noise pattern:** Add a regex to `NOISE_PATTERNS` in `agent.py`.

### Customization Points

| What | Where | How |
|------|-------|-----|
| Add noise filter | `agent.py:56` | Add regex to `NOISE_PATTERNS` |
| Add signal type | `detector.py` | Add keyword classification |
| Change relevance scoring | `detector.py` | Modify scoring algorithm |
| Add competitor auto-discovery | `detector.py` | Uses Harmonic's similar_companies |

---

## Deep Dive: Outreach Agent

**Location:** `agents/outreach/`

### Architecture

This agent has the most sophisticated personalization system:

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           OUTREACH PIPELINE                                │
│                                                                            │
│  ┌──────────────┐                                                         │
│  │  Company ID  │                                                         │
│  └──────┬───────┘                                                         │
│         │                                                                  │
│         ▼                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    │
│  │  ingest_company  │───▶│  select_contact  │───▶│detect_context_type│    │
│  │                  │    │                  │    │                  │    │
│  │  Harmonic +      │    │  Score founders  │    │  Match signals   │    │
│  │  Parallel +      │    │  by title,       │    │  to 18 context   │    │
│  │  Swarm           │    │  LinkedIn, bg    │    │  types           │    │
│  └──────────────────┘    └──────────────────┘    └────────┬─────────┘    │
│                                                           │               │
│                                                           ▼               │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    │
│  │  Investor        │    │   Style          │    │ Context Type     │    │
│  │  Profile         │───▶│   Examples       │───▶│ Config           │    │
│  │                  │    │                  │    │                  │    │
│  │  profiles.yaml   │    │  email_samples.md│    │ context_types.py │    │
│  └──────────────────┘    └──────────────────┘    └────────┬─────────┘    │
│                                                           │               │
│                                                           ▼               │
│                                              ┌───────────────────────┐    │
│                                              │  build_generation_    │    │
│                                              │  prompt               │    │
│                                              │                       │    │
│                                              │  System + User +      │    │
│                                              │  Examples + Context   │    │
│                                              └───────────┬───────────┘    │
│                                                          │                │
│                                                          ▼                │
│                                              ┌───────────────────────┐    │
│                                              │     Claude LLM        │    │
│                                              │  (Sonnet 4.5)         │    │
│                                              └───────────┬───────────┘    │
│                                                          │                │
│                                                          ▼                │
│                                              ┌───────────────────────┐    │
│                                              │   Email / LinkedIn    │    │
│                                              │   Message Output      │    │
│                                              └───────────────────────┘    │
└───────────────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose | When to modify |
|------|---------|----------------|
| `agent.py` | CLI entry point | Adding CLI flags |
| `generator.py` | Core generation pipeline | Changing generation logic |
| `context.py` | Investor profile loading | Adding investors |
| `context_types.py` | Context type detection | Adding outreach scenarios |
| `prompts.py` | Prompt building | Changing prompt structure |
| `profiles.yaml` | Investor voice profiles | Adding/editing investors |
| `docs/email_samples.md` | Style examples | Adding example emails |

### Investor Profiles

Each investor has a detailed profile in `profiles.yaml`:

```yaml
ashley:
  full_name: "Ashley Jepson"
  role: "Investor & Engineer, Data and AI Infrastructure"

  focus_areas:
    - "data infrastructure"
    - "AI infrastructure"
    - "agentic AI"

  tone: >
    Technical and intellectually curious. Ashley writes with genuine
    enthusiasm for the technical details...

  intro_patterns:
    default: "I'm an investor focused on data and AI infrastructure at NEA"
    engineering_lead: "I'm an investor and engineer focused on..."

  structural_pattern: >
    Personalized hook → Deep technical context → Self-introduction → Soft ask

  sign_off_options:
    - "Best,\nAshley"
    - "Ashley"

  portfolio_companies_to_reference:
    - "Perplexity"
    - "Databricks"
```

**Available investors:** `ashley`, `tiffany`, `danielle`, `madison`

### Context Types (18 total)

The agent auto-detects which "context type" fits best based on available signals:

| Context Type | When used | Email pattern |
|-------------|-----------|---------------|
| `thesis_driven_deep_dive` | Technical product alignment | Deep hook → Thesis → Architecture → Ask |
| `cold_technical_interest` | Product curiosity | Self-intro → Technical interest → Roadmap → Ask |
| `cold_funding_congrats` | Recent funding round | Congrats → Thesis → Interest → Ask |
| `event_based_warm_intro` | Met at conference | Event reference → Interest → Ask |
| `stealth_founder_outreach` | No public company | Founder background → Thesis → Ask |
| ... | (13 more) | |

### Customization Points

| What | Where | How |
|------|-------|-----|
| Add investor profile | `profiles.yaml` | Add new YAML block |
| Add email examples | `docs/email_samples.md` | Add with YAML metadata |
| Add context type | `context_types.py` | Add enum + config |
| Change LLM model | `generator.py:59` | `DEFAULT_LLM_MODEL` |
| Change contact selection | `generator.py:67` | Modify `select_contact()` |

### Stealth Mode

For founders without a public company:

```bash
python -m agents.outreach.agent \
  --stealth-mode \
  --founder-linkedin "https://linkedin.com/in/someone" \
  --founder-notes "Building something in AI infra" \
  --investor ashley
```

This bypasses company lookup and uses Swarm to enrich the founder's background.

---

## The Data Layer

### Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA PERSISTENCE                              │
│                                                                      │
│   ┌─────────────────────────┐    ┌─────────────────────────────┐   │
│   │       SQLite            │    │         Supabase            │   │
│   │    (Local Cache)        │    │     (Cloud Storage)         │   │
│   │                         │    │                             │   │
│   │  • company_core         │    │  • briefing_history         │   │
│   │  • founders             │    │  • outreach_history         │   │
│   │  • news                 │    │  • digest_history           │   │
│   │  • key_signals          │    │  • watched_companies        │   │
│   │                         │    │  • company_signals          │   │
│   │  Fast local queries     │    │  • audit_logs               │   │
│   │  Development mode       │    │  • investors                │   │
│   │                         │    │                             │   │
│   └─────────────────────────┘    │  Multi-user access          │   │
│                                  │  Production storage          │   │
│                                  │  Full audit trail            │   │
│                                  └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Database Files

| File | Purpose |
|------|---------|
| `core/database.py` | SQLite ORM, dataclasses, bundle assembly |
| `services/history.py` | Supabase history storage |
| `migrations/*.sql` | Supabase schema migrations |

### Data Sync

Data flows from APIs → SQLite → Supabase:

```python
# In tools/company_tools.py
sync_company_to_supabase(company_core)
sync_founders_to_supabase(company_id, founders)
sync_news_to_supabase(company_id, news)
```

---

## External API Integrations

### API Client Locations

All clients are in `core/clients/`:

| Client | File | Purpose | Required |
|--------|------|---------|----------|
| Harmonic | `harmonic.py` | Company data, founders, metrics | Yes |
| Parallel Search | `parallel_search.py` | News articles | Optional |
| Tavily | `tavily.py` | Website intelligence | Optional |
| Swarm | `swarm.py` | Founder backgrounds | Optional |
| Supabase | `supabase_client.py` | Cloud storage | Yes |

### API Client Pattern

All clients follow the same pattern:

```python
class SomeClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SOME_API_KEY")
        if not self.api_key:
            raise ValueError("SOME_API_KEY required")

    @retry_with_backoff(max_retries=3)
    def some_method(self, param: str) -> SomeResult:
        response = requests.get(...)
        return self._parse_response(response)
```

### Adding a New API Client

1. Create `core/clients/new_client.py`
2. Implement with retry logic from `core/resilience.py`
3. Add to `core/clients/__init__.py`
4. Integrate in `tools/company_tools.py`

---

## Customization Points

### Quick Reference: Where to Change Things

| I want to... | File | Line/Section |
|--------------|------|--------------|
| Change the LLM model (briefing) | `agents/meeting_briefing/agent.py` | Line 99 |
| Change the LLM model (outreach) | `agents/outreach/generator.py` | Line 59 |
| Add a new investor profile | `agents/outreach/profiles.yaml` | Add new block |
| Add email style examples | `docs/email_samples.md` | Add with YAML metadata |
| Add a noise filter (news) | `agents/news_aggregator/agent.py` | Line 56 |
| Change briefing output format | `agents/meeting_briefing/agent.py` | Lines 897-977 |
| Add a new signal type | `agents/news_aggregator/detector.py` | Keyword classification |
| Add a new data source | `agents/meeting_briefing/agent.py` | Implement `DataSource` |
| Change cost tracking | `core/tracking.py` | `SERVICE_COSTS` dict |

### Prompt Modifications

**Meeting Briefing system prompt:** `agents/meeting_briefing/agent.py`, lines 897-977

**Outreach prompt building:** `agents/outreach/prompts.py`

Both prompts use few-shot examples for style consistency.

---

## Current Capabilities & Limitations

### What Works Well

| Capability | Notes |
|------------|-------|
| Company lookup by domain | `stripe.com`, `openai.com` — very reliable |
| Company lookup by LinkedIn | `linkedin.com/company/stripe` — works well |
| Founder extraction | Names, titles, LinkedIn URLs |
| News aggregation | Last 30 days, multiple sources |
| Signal classification | Funding, hiring, product launches |
| Personalized outreach | 4 investor profiles, 18 context types |
| Citation tracking | All facts traced to sources |
| Cost tracking | Per-company and aggregate costs |

### Current Limitations

| Limitation | Why | Workaround |
|------------|-----|------------|
| **Small/stealth companies** | Harmonic may not have data | Use stealth mode for outreach |
| **Non-English content** | News search is English-only | None currently |
| **Real-time signals** | Batch processing, not streaming | Run `--check` frequently |
| **Founder backgrounds** | Swarm API may be incomplete | Manual enrichment |
| **No pitch deck parsing** | Not yet implemented | Future enhancement |
| **No CRM integration** | Standalone system | Future enhancement |
| **Single-threaded** | Agents run sequentially | Future: async parallelization |

### API Limitations

| API | Rate Limit | Gotchas |
|-----|------------|---------|
| Harmonic | 10 RPS | Some companies not in database |
| Parallel Search | Varies | News quality varies by company |
| Swarm | Unknown | Profile coverage incomplete |
| Tavily | 1K free/month | Website changes may not be detected |

---

## Future Improvement Areas

### High-Impact Enhancements

1. **Async parallelization** — Run multiple company lookups concurrently
2. **CRM integration** — Sync with Affinity/Salesforce
3. **Pitch deck parsing** — Extract data from PDFs
4. **Slack/email delivery** — Push digests automatically
5. **Feedback loop** — Learn from edited messages

### Code Quality Improvements

1. **More comprehensive tests** — Currently 366 tests, but coverage gaps exist
2. **Type hints** — Some files missing proper typing
3. **Error handling** — Some edge cases not covered
4. **Logging consistency** — Mixed logging patterns

### Architecture Improvements

1. **Event-driven signals** — Replace polling with webhooks
2. **Redis caching** — Faster than SQLite for hot data
3. **Background workers** — Celery/RQ for async jobs
4. **API versioning** — For future breaking changes

---

## Common Tasks & Recipes

### Add a New Investor Profile

1. Add to `agents/outreach/profiles.yaml`:
```yaml
newinvestor:
  full_name: "New Person"
  role: "Partner, Consumer Tech"
  focus_areas:
    - "consumer"
    - "marketplaces"
  tone: >
    Conversational and warm. Uses casual language...
  intro_patterns:
    default: "I'm a partner at NEA focused on consumer tech"
  sign_off_options:
    - "Best,\nNew"
  portfolio_companies_to_reference:
    - "Company1"
    - "Company2"
```

2. Add email samples to `docs/email_samples.md`:
```markdown
---

```yaml
investor: newinvestor
context_type: cold_technical_interest
format: email
```

Subject: [Subject line]

[Email body...]

---
```

3. Test: `python -m agents.outreach.agent --company example.com --investor newinvestor`

### Add a New Company to News Watchlist

```bash
# Add portfolio company
python -m agents.news_aggregator.agent --add stripe.com --name Stripe --category portfolio

# Add competitor
python -m agents.news_aggregator.agent --add adyen.com --name Adyen --category competitor
```

### Run a Full Briefing Pipeline

```bash
# With tracing for debugging
LANGSMITH_TRACING=true python -m agents.meeting_briefing.agent stripe.com

# Save output
python -m agents.meeting_briefing.agent stripe.com > briefing.md
```

### Debug a Failing Company Lookup

```python
# In Python REPL
from core.clients.harmonic import HarmonicClient

client = HarmonicClient()
result = client.lookup_company(domain="example.com")
print(result)  # See what Harmonic returns
```

### Check API Costs

```python
from core.tracking import get_cost_summary

costs = get_cost_summary(days=30)
print(f"Total: ${costs['total_cost']:.2f}")
print(f"Per company: ${costs['cost_per_company']:.4f}")
```

### Export Evaluation Results

```bash
python -m evaluation.run_eval \
  --companies stripe.com airbnb.com openai.com \
  --output results/eval.json \
  --validate-citations
```

---

## Getting Help

- **README.md** — Quick start and configuration
- **Tests** — `pytest tests/ -v` to see what's tested
- **LangSmith** — Enable tracing for debugging LLM calls
- **Logs** — Check `logs/` directory for errors

---

*Last updated: March 2026*
