"""
Services module for NEA AI Agents.

Provides:
- FastAPI backend for Lovable frontend
- Briefing history persistence using Supabase
"""

from services.history import BriefingHistoryDB, BriefingRecord

__all__ = ["BriefingHistoryDB", "BriefingRecord"]
