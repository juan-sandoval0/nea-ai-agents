# NEA AI Agents

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Tests](https://img.shields.io/badge/tests-366%20passing-brightgreen.svg)

AI agents for venture capital workflows built with LangChain and LangGraph.

---

## Table of Contents

- [Problem](#problem)
- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [The Three Agents](#the-three-agents)
  - [Meeting Briefing Agent](#1-meeting-briefing-agent)
  - [News Aggregator Agent](#2-news-aggregator-agent)
  - [Outreach Agent](#3-outreach-agent)
- [Configuration Guide](#configuration-guide)
  - [Environment Variables](#environment-variables)
  - [Changing Models](#changing-models)
  - [Changing API Providers](#changing-api-providers)
- [Costs & Pricing](#costs--pricing)
- [Project Structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Team](#team)

---

## Problem

**VC investors spend 2-4 hours preparing for each meeting** — researching companies, synthesizing signals, and drafting talking points. This is repetitive, error-prone, and doesn't scale.

**NEA AI Agents automates meeting briefing preparation** by:
- Aggregating company data from Harmonic, Tavily, and Parallel Search
- Detecting key signals (funding, hiring, product launches)
- Generating structured briefings with citations and source attribution
- Creating personalized outreach messages

The result: **meeting prep in minutes, not hours**, with full traceability.

---

## Quick Start

```bash
# 1. Clone and setup
cd nea-ai-agents
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys (see Configuration Guide below)

# 4. Run an agent
python -m agents.meeting_briefing.agent stripe.com
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           NEA AI Agents                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│   │    Meeting      │  │      News       │  │    Outreach     │    │
│   │   Briefing      │  │   Aggregator    │  │     Agent       │    │
│   │    Agent        │  │     Agent       │  │                 │    │
│   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │
│            │                    │                    │              │
│            └────────────────────┼────────────────────┘              │
│                                 │                                    │
│                    ┌────────────▼────────────┐                      │
│                    │     Shared Services     │                      │
│                    │  • company_tools.py     │                      │
│                    │  • core/clients/*       │                      │
│                    │  • core/database.py     │                      │
│                    └────────────┬────────────┘                      │
│                                 │                                    │
├─────────────────────────────────┼────────────────────────────────────┤
│                    External APIs & Services                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Harmonic │ │  Tavily  │ │ Parallel │ │  Swarm   │ │  Claude  │  │
│  │(company) │ │(website) │ │ (news)   │ │(founders)│ │  (LLM)   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      Supabase (PostgreSQL)                    │   │
│  │   • briefing_history  • watched_companies  • outreach_history│   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Input**: Company URL (e.g., `stripe.com`)
2. **Data Ingestion**: `tools/company_tools.py` fetches from Harmonic, Parallel Search, Swarm
3. **Processing**: Agent-specific LangGraph workflow processes data
4. **LLM Synthesis**: Claude generates final output (briefing, message, digest)
5. **Storage**: Results saved to Supabase for history/audit

---

## The Three Agents

### 1. Meeting Briefing Agent

**Purpose**: Generate comprehensive meeting prep documents for investor meetings.

**Location**: `agents/meeting_briefing/agent.py`

**How it works**:
```
URL Input → Validate Company → [PARALLEL: Profile | News | Signals] → Synthesize Briefing
```

The agent uses LangGraph to run three retrieval operations in parallel, then synthesizes everything with Claude into a structured briefing.

**Run it**:
```bash
# Basic usage
python -m agents.meeting_briefing.agent stripe.com

# With LangSmith tracing
LANGSMITH_TRACING=true python -m agents.meeting_briefing.agent stripe.com
```

**Output sections**:
- TL;DR (2-3 sentences)
- Why This Meeting Matters
- Company Snapshot (table)
- Founders (with backgrounds)
- Key Signals
- In the News
- Meeting Prep (questions + next steps)

**Key files**:
| File | Purpose |
|------|---------|
| `agent.py` | Main workflow, LangGraph state machine |
| `harmonic_source.py` | Harmonic API data source implementation |

---

### 2. News Aggregator Agent

**Purpose**: Track portfolio companies and competitors for signals (funding, hires, launches).

**Location**: `agents/news_aggregator/agent.py`

**How it works**:
1. Maintains a watchlist of portfolio companies + competitors
2. Periodically scans Harmonic (metrics) + Parallel Search (news)
3. Classifies signals, scores relevance, filters noise
4. Generates investor digest

**Run it**:
```bash
# Add a company to watchlist
python -m agents.news_aggregator.agent --add stripe.com --name Stripe --category portfolio

# Check for new signals
python -m agents.news_aggregator.agent --check

# Generate digest (last 7 days)
python -m agents.news_aggregator.agent --digest --days 7

# Show alerts only
python -m agents.news_aggregator.agent --alerts

# List all watched companies
python -m agents.news_aggregator.agent --list
```

**Signal types detected**:
| Type | Source | Description |
|------|--------|-------------|
| `funding` | Harmonic/News | Funding rounds |
| `acquisition` | News | M&A activity |
| `team_change` | News | Executive hires/departures |
| `product_launch` | News | Product announcements |
| `hiring_expansion` | Harmonic | Headcount changes |
| `web_traffic` | Harmonic | Traffic changes |

**Key files**:
| File | Purpose |
|------|---------|
| `agent.py` | CLI and orchestration |
| `detector.py` | Signal detection logic |
| `database.py` | Watchlist storage (Supabase) |
| `investor_digest.py` | Digest generation |

---

### 3. Outreach Agent

**Purpose**: Generate personalized cold outreach emails/LinkedIn messages.

**Location**: `agents/outreach/agent.py`

**How it works**:
1. Ingests company data (reuses `company_tools.py`)
2. Auto-selects best founder contact
3. Detects "context type" (thesis-driven, problem-solving, etc.)
4. Loads investor voice profile + style examples
5. Generates personalized message via Claude

**Run it**:
```bash
# Generate email (default investor: ashley)
python -m agents.outreach.agent --company stripe.com --format email

# As different investor
python -m agents.outreach.agent --company stripe.com --investor madison

# LinkedIn message
python -m agents.outreach.agent --company stripe.com --format linkedin

# Preview data without generating
python -m agents.outreach.agent --company stripe.com --preview

# List available investor profiles
python -m agents.outreach.agent --list-profiles
```

**Context types**:
- `thesis_driven_deep_dive` - Investment thesis alignment
- `problem_solving_discussion` - Pain point focused
- `founder_background_connection` - Shared background hook
- `stealth_founder_outreach` - Stealth mode (no public company info)

**Key files**:
| File | Purpose |
|------|---------|
| `agent.py` | CLI entry point |
| `generator.py` | Core generation pipeline |
| `context.py` | Investor profiles |
| `context_types.py` | Context type detection |
| `prompts.py` | Prompt building |

---

## Configuration Guide

### Environment Variables

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

**Required API Keys**:

| Variable | Service | Required For | Get it from |
|----------|---------|--------------|-------------|
| `ANTHROPIC_API_KEY` | Claude LLM | All agents | [console.anthropic.com](https://console.anthropic.com/) |
| `HARMONIC_API_KEY` | Company data | Meeting briefing, News aggregator | [console.harmonic.ai](https://console.harmonic.ai/) |
| `SUPABASE_URL` | Database | History storage | [supabase.com](https://supabase.com/) |
| `SUPABASE_SERVICE_KEY` | Database | History storage | Supabase dashboard |

**Optional API Keys**:

| Variable | Service | Purpose | Get it from |
|----------|---------|---------|-------------|
| `TAVILY_API_KEY` | Website intelligence | Website signals | [tavily.com](https://tavily.com/) (FREE: 1K credits/month) |
| `PARALLEL_API_KEY` | News search | News articles | [parallel.ai](https://parallel.ai/) |
| `SWARM_API_KEY` | Founder profiles | Background enrichment | [theswarm.com](https://theswarm.com/) |
| `LANGSMITH_API_KEY` | Tracing | Debugging/observability | [smith.langchain.com](https://smith.langchain.com/) |

**Graceful Degradation**: Missing optional keys disable features but don't crash the system.

### Changing Models

Models are configured in each agent file. Here's where to change them:

**Meeting Briefing Agent** (`agents/meeting_briefing/agent.py:99`):
```python
DEFAULT_LLM_MODEL = "claude-sonnet-4-6"  # Change this
```

**Outreach Agent** (`agents/outreach/generator.py:59`):
```python
DEFAULT_LLM_MODEL = "claude-sonnet-4-5-20250929"  # Change this
```

**To switch models**, change the string to any supported model:

| Model | Provider | Best For | Cost |
|-------|----------|----------|------|
| `claude-sonnet-4-6` | Anthropic | Meeting briefings (structured output) | ~$3/1M input, $15/1M output |
| `claude-sonnet-4-5-20250929` | Anthropic | Outreach (creative writing) | ~$3/1M input, $15/1M output |
| `claude-3-5-haiku-20241022` | Anthropic | Fast, cheap tasks | ~$0.25/1M input, $1.25/1M output |
| `gpt-4o` | OpenAI | Alternative (legacy) | ~$2.50/1M input, $10/1M output |
| `gpt-4o-mini` | OpenAI | Cheap alternative | ~$0.15/1M input, $0.60/1M output |

**Why Claude over OpenAI?** The project migrated to Claude for:
- Better structured output formatting
- More consistent citation behavior
- Comparable cost, better quality for synthesis tasks

### Changing API Providers

**To add a new data source**, implement the `DataSource` protocol in `agents/meeting_briefing/agent.py`:

```python
class MyNewDataSource:
    def get_company_profile(self, url: str) -> RetrievalResult:
        # Implement
        pass

    def get_recent_news(self, url: str, days: int = 30) -> RetrievalResult:
        # Implement
        pass

    def get_key_signals(self, url: str) -> RetrievalResult:
        # Implement
        pass

    def list_companies(self) -> list[str]:
        return ["*"]  # Dynamic lookup
```

**To replace an existing client**, edit the relevant file in `core/clients/`:

| Client | File | Replace to change... |
|--------|------|---------------------|
| Harmonic | `core/clients/harmonic.py` | Company data source |
| Tavily | `core/clients/tavily.py` | Website intelligence |
| Parallel Search | `core/clients/parallel_search.py` | News search |
| Swarm | `core/clients/swarm.py` | Founder backgrounds |

---

## Costs & Pricing

### Per-Company Costs (Estimated)

| Service | Cost | Notes |
|---------|------|-------|
| **Claude (Briefing)** | ~$0.02-0.05 | Varies by output length |
| **Claude (Outreach)** | ~$0.01-0.02 | Shorter outputs |
| **Harmonic** | Included | Subscription-based |
| **Tavily** | ~$0.02 | ~2 credits per crawl |
| **Parallel Search** | ~$0.01 | Per search query |
| **Swarm** | Varies | Per profile lookup |

### Monthly Projections

| Scale | Companies/Month | Estimated Cost |
|-------|-----------------|----------------|
| Light | 50 | ~$5-10 |
| Medium | 200 | ~$15-30 |
| Heavy | 500 | ~$35-60 |

### Cost Tracking

The system tracks costs automatically:
```python
from core.tracking import get_cost_summary

costs = get_cost_summary(days=30)
print(f"Total: ${costs['total_cost']:.2f}")
print(f"Per company: ${costs['cost_per_company']:.4f}")
```

---

## Project Structure

```
nea-ai-agents/
├── agents/                      # The three AI agents
│   ├── meeting_briefing/        # Meeting prep briefings
│   │   ├── agent.py             # Main LangGraph workflow
│   │   ├── harmonic_source.py   # Harmonic API integration
│   │   └── chroma_db/           # Local vector cache
│   ├── news_aggregator/         # Signal tracking
│   │   ├── agent.py             # CLI and orchestration
│   │   ├── detector.py          # Signal detection
│   │   ├── database.py          # Supabase storage
│   │   └── investor_digest.py   # Digest generation
│   └── outreach/                # Personalized outreach
│       ├── agent.py             # CLI entry point
│       ├── generator.py         # Message generation
│       ├── context.py           # Investor profiles
│       └── prompts.py           # Prompt templates
│
├── core/                        # Shared infrastructure
│   ├── clients/                 # API client wrappers
│   │   ├── harmonic.py          # Harmonic.ai client
│   │   ├── tavily.py            # Tavily client
│   │   ├── parallel_search.py   # Parallel Search client
│   │   ├── swarm.py             # Swarm client
│   │   └── supabase_client.py   # Supabase client
│   ├── database.py              # SQLite ORM + schemas
│   ├── schemas.py               # Pydantic validation
│   ├── tracking.py              # Cost/usage tracking
│   ├── observability.py         # Logging/tracing
│   └── security.py              # Input validation
│
├── services/                    # Backend services
│   ├── api.py                   # FastAPI server
│   ├── history.py               # History storage
│   └── job_manager.py           # Background jobs
│
├── tools/                       # Shared tools
│   └── company_tools.py         # Multi-source data ingestion
│
├── evaluation/                  # Testing framework
│   └── run_eval.py              # Evaluation harness
│
├── scripts/                     # Maintenance scripts
│   └── cleanup_history.py       # Database cleanup
│
├── tests/                       # Test suite (366+ tests)
├── migrations/                  # Supabase migrations
├── observability/               # LangSmith integration
├── data/                        # Local data (gitignored)
└── logs/                        # Log files (gitignored)
```

---

## Development

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test files
pytest tests/test_harmonic_client.py -v
pytest tests/test_integration_pipeline.py -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

### API Server

```bash
# Start the FastAPI server
uvicorn services.api:app --reload --port 8000

# Endpoints:
# POST /api/briefing          - Generate briefing
# GET  /api/briefings         - List briefings
# GET  /api/briefings/{id}    - Get specific briefing
```

### Database Setup (Supabase)

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. Run migrations in `migrations/` via SQL editor
3. Add credentials to `.env`

### History Cleanup

Records older than 30 days are automatically cleaned:

```bash
# Preview (dry run)
python scripts/cleanup_history.py --dry-run

# Run cleanup
python scripts/cleanup_history.py

# Set up daily cron job
crontab -e
# Add: 0 2 * * * /path/to/python scripts/cleanup_history.py >> logs/cleanup.log 2>&1
```

### LangSmith Tracing

Enable for debugging:

```bash
# In .env
LANGSMITH_API_KEY=your_key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=meeting-briefing-mvp

# Run with tracing
LANGSMITH_TRACING=true python -m agents.meeting_briefing.agent stripe.com
```

---

## Troubleshooting

### Common Issues

**"Company not found in Harmonic"**
- Check the URL format (use domain like `stripe.com`, not full URL)
- Verify `HARMONIC_API_KEY` is set
- Company may not exist in Harmonic's database

**"ANTHROPIC_API_KEY not set"**
- Add your key to `.env`
- Verify the file is named `.env` (not `.env.example`)

**Empty news results**
- Check `PARALLEL_API_KEY` is set
- News may not exist for smaller companies

**Outreach generation fails**
- Run without `--skip-ingest` to fetch fresh data
- Check that founders exist in the database

### Graceful Degradation

| Missing Key | Behavior |
|-------------|----------|
| `HARMONIC_API_KEY` | **Blocks briefing** - required for company lookup |
| `ANTHROPIC_API_KEY` | **Blocks generation** - required for LLM |
| `TAVILY_API_KEY` | Website signals disabled; placeholder added |
| `PARALLEL_API_KEY` | News search disabled; empty results |
| `SWARM_API_KEY` | Founder backgrounds not enriched |

---

## Team

- Ana Garza
- Ellie Brew
- Juan Sandoval
- Luke Shuman

---

## License

MIT License - see [LICENSE](LICENSE) for details.
