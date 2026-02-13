"""
Services module for NEA AI Agents.

Provides briefing history persistence using Supabase.
"""

from services.history import BriefingHistoryDB, BriefingRecord

__all__ = ["BriefingHistoryDB", "BriefingRecord"]
