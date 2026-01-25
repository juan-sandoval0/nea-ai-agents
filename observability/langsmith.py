"""
LangSmith Tracing Helpers
=========================
Minimal, non-invasive tracing utilities for the meeting briefing agent.

Enable/disable via environment variables:
- LANGSMITH_TRACING=true/false (default: false)
- LANGSMITH_PROJECT="meeting-briefing-mvp"
- LANGSMITH_API_KEY (required when tracing enabled)
"""

import os
import time
import functools
from contextlib import contextmanager
from typing import Any, Callable, Optional
from uuid import uuid4


def tracing_enabled() -> bool:
    """Check if LangSmith tracing is enabled via environment variable."""
    return os.getenv("LANGSMITH_TRACING", "false").lower() == "true"


def get_project_name() -> str:
    """Get the LangSmith project name from environment."""
    return os.getenv("LANGSMITH_PROJECT", "meeting-briefing-mvp")


def get_run_config(
    company_name: str,
    run_id: Optional[str] = None,
    extra_meta: Optional[dict] = None
) -> dict:
    """
    Build a run configuration dict with standard metadata.

    Args:
        company_name: Normalized company name
        run_id: Optional run ID (generated if not provided)
        extra_meta: Additional metadata to include

    Returns:
        Configuration dict for LangSmith runs
    """
    config = {
        "run_id": run_id or str(uuid4()),
        "metadata": {
            "company_name": company_name,
            **(extra_meta or {})
        },
        "project_name": get_project_name(),
    }
    return config


class TracingContext:
    """
    Context manager for tracking step timing and metadata.

    Works regardless of whether LangSmith is enabled - always tracks
    timing and metadata locally, only sends to LangSmith if enabled.
    """

    def __init__(
        self,
        run_id: str,
        company_name: str,
        time_window_days: Optional[int] = None
    ):
        self.run_id = run_id
        self.company_name = company_name
        self.time_window_days = time_window_days
        self.retrieval_counts = {"profile_k": 0, "news_k": 0, "signals_k": 0}
        self.retrieval_doc_ids = {"profile": [], "news": [], "signals": []}
        self.step_timings = {}
        self.total_start_time = None
        self.total_elapsed_ms = 0
        self._run_tree = None

    def start(self):
        """Start the tracing context."""
        self.total_start_time = time.perf_counter()

        if tracing_enabled():
            try:
                from langsmith import Client
                from langsmith.run_trees import RunTree

                self._run_tree = RunTree(
                    name="meeting_briefing_run",
                    run_type="chain",
                    inputs={"company_name": self.company_name},
                    project_name=get_project_name(),
                    id=self.run_id,
                )
                self._run_tree.post()
            except ImportError:
                pass
            except Exception:
                # Fail silently if LangSmith unavailable
                pass

    def end(self, output: Any = None, error: Optional[str] = None):
        """End the tracing context and finalize metadata."""
        if self.total_start_time:
            self.total_elapsed_ms = int(
                (time.perf_counter() - self.total_start_time) * 1000
            )

        if self._run_tree:
            try:
                self._run_tree.end(
                    outputs={"result": str(output)[:1000] if output else None},
                    error=error,
                    metadata=self.get_metadata(),
                )
                self._run_tree.patch()
            except Exception:
                pass

    def get_metadata(self) -> dict:
        """Get the full metadata dict for this run."""
        return {
            "company_name": self.company_name,
            "run_id": self.run_id,
            "retrieval_counts": self.retrieval_counts.copy(),
            "retrieval_doc_ids": {k: v.copy() for k, v in self.retrieval_doc_ids.items()},
            "time_window_days": self.time_window_days,
            "step_timings_ms": self.step_timings.copy(),
            "total_elapsed_ms": self.total_elapsed_ms,
        }

    def record_retrieval(
        self,
        retriever_type: str,
        doc_count: int,
        doc_ids: Optional[list] = None
    ):
        """Record retrieval statistics."""
        key = f"{retriever_type}_k"
        if key in self.retrieval_counts:
            self.retrieval_counts[key] = doc_count
        if retriever_type in self.retrieval_doc_ids:
            self.retrieval_doc_ids[retriever_type] = doc_ids or []

    def record_step_timing(self, step_name: str, elapsed_ms: int):
        """Record timing for a specific step."""
        self.step_timings[step_name] = elapsed_ms


def trace_step(name: str, run_type: str = "tool"):
    """
    Decorator to trace a function call.

    If tracing is disabled, simply executes the function.
    If enabled, wraps with LangSmith tracing.

    Args:
        name: Name of the step for tracing
        run_type: Type of run ("tool", "llm", "chain", etc.)

    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()

            if not tracing_enabled():
                result = func(*args, **kwargs)
                return result

            try:
                from langsmith import traceable

                @traceable(name=name, run_type=run_type)
                def traced_func(*a, **kw):
                    return func(*a, **kw)

                result = traced_func(*args, **kwargs)
            except ImportError:
                result = func(*args, **kwargs)
            except Exception:
                # Fall back to untraced execution
                result = func(*args, **kwargs)

            return result

        return wrapper
    return decorator


@contextmanager
def trace_context(
    name: str,
    run_type: str = "tool",
    inputs: Optional[dict] = None,
    parent_run: Optional[Any] = None
):
    """
    Context manager for tracing a block of code.

    Args:
        name: Name of the traced block
        run_type: Type of run
        inputs: Input parameters to log
        parent_run: Optional parent RunTree for nesting

    Yields:
        Dict with timing info that can be updated with outputs
    """
    start_time = time.perf_counter()
    context = {"elapsed_ms": 0, "outputs": None, "error": None}
    run_tree = None

    if tracing_enabled():
        try:
            from langsmith.run_trees import RunTree

            run_tree = RunTree(
                name=name,
                run_type=run_type,
                inputs=inputs or {},
                project_name=get_project_name(),
                parent_run=parent_run,
            )
            run_tree.post()
        except ImportError:
            pass
        except Exception:
            pass

    try:
        yield context
    except Exception as e:
        context["error"] = str(e)
        raise
    finally:
        context["elapsed_ms"] = int((time.perf_counter() - start_time) * 1000)
        if run_tree:
            try:
                run_tree.end(
                    outputs=context.get("outputs"),
                    error=context.get("error"),
                )
                run_tree.patch()
            except Exception:
                pass


def get_langsmith_client():
    """
    Get a LangSmith client if tracing is enabled.

    Returns:
        LangSmith Client or None if tracing disabled/unavailable
    """
    if not tracing_enabled():
        return None

    try:
        from langsmith import Client
        return Client()
    except ImportError:
        return None
    except Exception:
        return None
