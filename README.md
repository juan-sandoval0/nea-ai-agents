hello

# NEA AI Agents

AI agents for venture capital workflows built with LangChain and LangGraph.

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
