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

# Run meeting briefing tool tests
pytest tests/test_tools.py -v
```
