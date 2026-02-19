# Personalized Outreach Agent - Cold outreach message generation for VC investors

from .generator import generate_outreach
from .context import get_investor_context, load_samples, InvestorProfile, EmailSample
from .context_types import ContextType, detect_context_type
from .prompts import build_generation_prompt

__all__ = [
    "generate_outreach",
    "get_investor_context",
    "load_samples",
    "InvestorProfile",
    "EmailSample",
    "ContextType",
    "detect_context_type",
    "build_generation_prompt",
]
