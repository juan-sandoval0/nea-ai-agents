# NEA AI Agents

AI agents for venture capital workflows built with LangChain and LangGraph.

## Quick Start

```bash
# Install all dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# Run the meeting briefing agent
python -m agents.meeting_briefing.agent
```

## Description

This project provides AI agents to automate and enhance venture capital workflows, including:
- Meeting briefing preparation
- Pitch deck parsing and analysis
- Company tracking and monitoring

## Team Members

- Ana Garza
- Ellie Brew
- Juan Sandoval
- Luke Shuman

## Setup Instructions

1. **Clone the repository** (if applicable) or navigate to the project directory:
   ```bash
   cd nea-ai-agents
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**:
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Set up environment variables**:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and add your API keys:
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `LANGCHAIN_API_KEY`: Your LangSmith API key (optional, for tracing)

6. **Run the demo agent**:
   ```bash
   python main.py
   ```

## Project Structure

```
nea-ai-agents/
├── agents/              # AI agent implementations
│   ├── meeting_briefing/
│   ├── deck_parser/
│   └── company_tracker/
├── tools/              # Custom tools for agents
├── data/               # Data files (gitignored)
├── notebooks/          # Jupyter notebooks for exploration
├── tests/              # Unit tests
└── main.py            # Demo entry point
```

## Development

To explore the agents interactively, use Jupyter notebooks:
```bash
jupyter notebook notebooks/01_getting_started.ipynb
```

## LangSmith Tracing

The meeting briefing agent supports full LangSmith tracing for debugging and evaluation.

### Environment Variables

Add these to your `.env` file:

```bash
# Required for tracing
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_TRACING=true          # Set to 'false' to disable (default: false)
LANGSMITH_PROJECT=meeting-briefing-mvp  # Project name in LangSmith
```

### What Gets Traced

When tracing is enabled, the following are logged to LangSmith:
- **Overall agent runs** - One trace per briefing request
- **LLM calls** - The synthesizer step that generates the briefing
- **Tool/retriever calls** - company_profile, news, and signals retrievers

### Custom Metadata

Each trace includes:
- `company_name` - Normalized company name
- `run_id` - Unique UUID for the run
- `retrieval_counts` - `{profile_k, news_k, signals_k}` document counts
- `retrieval_doc_ids` - Document IDs for each retriever
- `time_window_days` - News lookback window (if applicable)
- `elapsed_ms` - Timing for each step and total

### Running the Agent

```bash
# Without tracing
python -m agents.meeting_briefing.agent

# With tracing enabled
LANGSMITH_TRACING=true python -m agents.meeting_briefing.agent
```

## Evaluation Harness

Run the agent on company URLs and log results:

```bash
# Run evaluation on default URLs (stripe.com, airbnb.com, openai.com)
python -m agents.meeting_briefing.eval_harness

# With tracing enabled
LANGSMITH_TRACING=true python -m agents.meeting_briefing.eval_harness

# Save results to file
python -m agents.meeting_briefing.eval_harness --output results/eval_results.json

# Run on specific company URLs
python -m agents.meeting_briefing.eval_harness --urls stripe.com airbnb.com

# Also supports LinkedIn URLs
python -m agents.meeting_briefing.eval_harness --urls "linkedin.com/company/stripe"
```

### Viewing Results in LangSmith

1. Go to [LangSmith](https://smith.langchain.com)
2. Navigate to your project (default: `meeting-briefing-mvp`)
3. Filter by tags or metadata to compare runs across companies

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run observability tests only
pytest tests/test_observability.py -v

# Run client tests (Harmonic, Tavily, Parallel Search)
pytest tests/test_harmonic_client.py tests/test_tavily_client.py -v

# Run company tools tests
pytest tests/test_company_tools.py -v

# Run integration pipeline tests
pytest tests/test_integration_pipeline.py -v

# Run schema validation tests
pytest tests/test_schemas.py -v
```

## Known Issues and Edge Cases

### API Key Graceful Degradation

The system gracefully degrades when API keys are not set:

| Missing Key | Behavior |
|-------------|----------|
| `HARMONIC_API_KEY` | **Required** - Company profile lookup will fail |
| `TAVILY_API_KEY` | Website intelligence disabled; placeholder signal added |
| `NEWS_API_KEY` | News search disabled; empty news results |
| `OPENAI_API_KEY` | **Required** for briefing generation |

### Data Quality Edge Cases

1. **Harmonic `name: null`**: When company name is null in the API response, defaults to `"Unknown"`. Tests verify this in `test_harmonic_client.py`.

2. **Missing Optional Fields**: All optional fields (founding_date, hq, employee_count, etc.) gracefully default to `None`. The briefing shows "Not found in table" for missing data.

3. **Empty Founder Lists**: If no founders are found via Harmonic's people array, the system falls back to key executives (CEO, President).

4. **Stale Placeholder Signals**: When Tavily signals exist, stale "pending_tavily" placeholders are automatically filtered from the briefing output.

### Signal Types

Valid signal types and their sources:

| Signal Type | Source | Description |
|-------------|--------|-------------|
| `web_traffic` | Harmonic | 30-day traffic change |
| `hiring` | Harmonic | 90-day headcount change |
| `funding` | Harmonic | Last funding round info |
| `website_product` | Tavily | Product updates detected |
| `website_pricing` | Tavily | Pricing page changes |
| `website_team` | Tavily | Team page changes |
| `website_news` | Tavily | News/blog updates |
| `website_update` | Tavily | General website changes |
| `funding` | NewsAPI | Funding news articles |
| `acquisition` | NewsAPI | M&A news |
| `team_change` | NewsAPI | Executive hiring/departure news |
| `product_launch` | NewsAPI | Product announcement news |
| `partnership` | NewsAPI | Partnership news |
| `news_coverage` | NewsAPI | General news coverage |

### Citation and Source Tracking

Every data point includes source attribution:

- **CompanyCore**: `source_map` dict maps each field to its source
- **Founders**: `source` field indicates data origin (harmonic/manual_correction)
- **KeySignals**: `source` field (harmonic/tavily/news_api/pending_tavily)
- **NewsArticles**: `source` field (news_api)

### Error Handling

- **Harmonic API Errors**: 401 (auth), 404 (not found), 429 (rate limit) are caught and logged
- **Tavily API Errors**: Crawl failures result in fallback "unavailable" signal
- **NewsAPI Errors**: Search failures are caught; empty results returned
- **LLM Generation Errors**: Captured in `error` field of briefing result

### Output Validation

The system includes Pydantic schemas for output validation (`core/schemas.py`):

```python
from core.schemas import validate_briefing_result, validate_ingest_result

# Validate outputs
briefing = generate_briefing("stripe.com")
validated = validate_briefing_result(briefing)

ingest = ingest_company("stripe.com")
validated = validate_ingest_result(ingest)
```

## Data Analysis & Evaluation Framework

The system includes a comprehensive evaluation framework implementing the Data Analysis Plan.

### Running Evaluations

```bash
# Run comprehensive evaluation
python -m core.eval_harness --companies stripe.com airbnb.com --days 30

# Output to file
python -m core.eval_harness --companies stripe.com --output evaluation_report.md

# Summary only
python -m core.eval_harness --companies stripe.com --summary-only
```

### Evaluation Metrics

#### 1. Entity Resolution Accuracy
Measures whether the agent correctly identifies the intended company.

```python
from core.evaluation import evaluate_entity_resolution, GroundTruth

ground_truth = GroundTruth(
    company_id="stripe.com",
    company_name="Stripe",
    domain="stripe.com"
)
result = evaluate_entity_resolution("stripe.com", ground_truth=ground_truth)
print(f"Correct: {result.correct}, Confidence: {result.confidence:.2f}")
```

#### 2. Signal Coverage
Evaluates which information categories were successfully extracted.

```python
from core.evaluation import evaluate_signal_coverage

coverage = evaluate_signal_coverage("stripe.com")
print(f"Coverage: {coverage.coverage_rate:.1%}")
print(f"Found: {coverage.categories_found}")
print(f"Missing: {coverage.categories_missing}")
```

Signal categories: `product`, `pricing`, `team`, `news`, `funding`, `traction`, `website`

#### 3. Quality Scoring (Human Evaluation)
Human evaluators rate briefings on three dimensions (1-5 scale):

| Dimension | Description |
|-----------|-------------|
| **Clarity** | How clear and well-organized is the presentation? |
| **Correctness** | Is the information factually accurate? |
| **Usefulness** | How useful is this for investment decisions? |

```python
from core.quality_scoring import submit_quality_score, get_quality_stats

# Submit a score
submit_quality_score(
    company_id="stripe.com",
    evaluator="ana",
    clarity=4,
    correctness=5,
    usefulness=4,
    comments="Good overview, helpful for meeting prep"
)

# Get aggregate stats
stats = get_quality_stats("stripe.com")
print(f"Average: {stats.avg_overall:.2f}/5.0 ({stats.num_evaluations} evaluations)")
```

#### 4. Failure Mode Analysis
Documents and categorizes system failures.

```python
from core.failure_analysis import log_failure, FailureCategory, get_failure_stats

# Log a failure
log_failure(
    company_id="ambiguous.com",
    category=FailureCategory.NAMING_AMBIGUITY,
    description="Confused with Ambiguous Corp Inc",
    severity="medium"
)

# Get failure stats
stats = get_failure_stats(days=30)
print(f"Total failures: {stats.total_failures}")
print(f"By category: {stats.failures_by_category}")
```

Failure categories:
- `naming_ambiguity` - Multiple companies with similar names
- `domain_mapping` - Wrong domain-to-company mapping
- `missing_harmonic` - Harmonic data incomplete
- `tangential_content` - Retrieved content loosely related
- `api_error` - External API failures
- `data_quality` - Poor quality source data
- `llm_hallucination` - LLM generated unsupported content

#### 5. Cost Tracking
Tracks API costs and projects costs at scale.

```python
from core.tracking import get_cost_summary, project_costs_at_scale

# Get current costs
costs = get_cost_summary(days=30)
print(f"Total cost: ${costs['total_cost']:.2f}")
print(f"Cost per company: ${costs['cost_per_company']:.4f}")
print(f"Projected monthly: ${costs['projected_monthly']:.2f}")

# Project costs at NEA scale
projection = project_costs_at_scale(companies_per_month=500)
print(f"500 companies/month: ${projection['monthly_cost']:.2f}/month")
```

API cost estimates:
| Service | Unit | Cost |
|---------|------|------|
| Tavily | 2 credits/crawl | ~$0.02/company |
| OpenAI | tokens | ~$0.02/briefing |
| NewsAPI | search | ~$0.01/company |
| Harmonic | request | Subscription (included) |

### Unified Evaluation Entrypoint

The `evaluation/run_eval.py` module provides a single entrypoint for running all evaluation metrics:

```bash
# Run full evaluation on default companies
python -m evaluation.run_eval

# Run on specific companies
python -m evaluation.run_eval --companies stripe.com airbnb.com openai.com

# Output to JSON file
python -m evaluation.run_eval --output results/eval_2024.json

# Output to CSV
python -m evaluation.run_eval --output results/eval_2024.csv --format csv

# Include citation validation
python -m evaluation.run_eval --validate-citations

# Summary only
python -m evaluation.run_eval --summary-only
```

The evaluation runs:
- Entity resolution accuracy
- Retrieval relevance
- Signal coverage
- Quality scoring (from human evaluations)
- Failure-mode logging
- Cost metrics
- Citation presence validation (optional)

Output is a consolidated JSON/CSV with per-company and aggregate metrics.

### Citation Presence Validation

Validates that sources are properly cited in generated briefings:

```python
from evaluation.run_eval import validate_citations

result = validate_citations(
    company_id="stripe.com",
    briefing_text="According to TechCrunch, Stripe raised $6.5B...",
    source_documents=[
        {"url": "https://techcrunch.com/stripe-funding", "title": "Stripe Funding"}
    ]
)

print(f"Citation rate: {result['citation_rate']:.1%}")
print(f"Valid: {result['valid']}")
```

The validator:
- Detects when sources contribute facts
- Asserts in-text citations appear in output
- Flags hallucinated citations when no sources provided
- **Strict validation**: ALL contributing sources must be cited (100% requirement)

### Cost Persistence

Cost records are persisted to both JSON and CSV for analysis:

```python
from core.tracking import save_cost_record, export_cost_summary

# Save individual cost record
save_cost_record(
    company_id="stripe.com",
    service="tavily",
    operation="crawl",
    cost=0.02,
)

# Export cost summary
export_cost_summary("results/costs.json", days=30, format="json")
export_cost_summary("results/costs.csv", days=30, format="csv")
```

Files are stored in `data/cost_log.jsonl` and `data/cost_log.csv`.

### Evaluation Tests

```bash
# Run all evaluation framework tests
pytest tests/test_evaluation.py -v

# Run integration pipeline tests
pytest tests/test_integration_pipeline.py -v

# Run full test suite
pytest tests/ -v
```

## Failure Mode Tracking

The system includes infrastructure for logging and analyzing failure modes. The following categories are supported:

| Category | Description | How to Log |
|----------|-------------|------------|
| `naming_ambiguity` | Multiple companies with similar names | `FailureCategory.NAMING_AMBIGUITY` |
| `domain_mapping` | Wrong domain-to-company mapping | `FailureCategory.DOMAIN_MAPPING` |
| `missing_harmonic` | Harmonic data incomplete | `FailureCategory.MISSING_HARMONIC` |
| `tangential_content` | Retrieved content loosely related | `FailureCategory.TANGENTIAL_CONTENT` |
| `api_error` | External API failures | `FailureCategory.API_ERROR` |
| `data_quality` | Poor quality source data | `FailureCategory.DATA_QUALITY` |
| `llm_hallucination` | LLM generated unsupported content | `FailureCategory.LLM_HALLUCINATION` |

### Logging Failures

```python
from core.failure_analysis import log_failure, FailureCategory

# Log a failure
log_failure(
    company_id="example.com",
    category=FailureCategory.NAMING_AMBIGUITY,
    description="Resolved to wrong company",
    severity="medium",
    details={"expected": "Example Inc", "got": "Example Corp"}
)

# Generate failure report
from core.failure_analysis import generate_failure_report
report = generate_failure_report(days=30)
print(report)
```
