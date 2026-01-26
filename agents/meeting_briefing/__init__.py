"""Meeting Briefing Agent - Document ingestion and retrieval for VC meeting prep."""

# Lazy imports to avoid import-time crashes when dependencies are missing
# Use: from agents.meeting_briefing import MeetingBriefingAgent

MOCK_COMPANIES = [
    "Nexus AI",
    "Quantum Ledger",
    "Helix Therapeutics",
    "Terraflow",
    "Codelayer",
]


def __getattr__(name):
    """Lazy import for heavy dependencies."""
    if name == "DocumentIngestionPipeline":
        from .ingestion import DocumentIngestionPipeline
        return DocumentIngestionPipeline
    if name == "MeetingBriefingAgent":
        from .agent import MeetingBriefingAgent
        return MeetingBriefingAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DocumentIngestionPipeline", "MeetingBriefingAgent", "MOCK_COMPANIES"]
