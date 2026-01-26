"""
Tests for Observability Module
==============================
Unit tests for LangSmith tracing helpers.

Run with:
    pytest tests/test_observability.py -v
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestTracingEnabled(unittest.TestCase):
    """Tests for tracing_enabled() function."""

    def test_tracing_disabled_by_default(self):
        """When LANGSMITH_TRACING is not set, tracing should be disabled."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("LANGSMITH_TRACING", None)

            from observability.langsmith import tracing_enabled
            # Need to reimport to pick up env change
            import importlib
            import observability.langsmith
            importlib.reload(observability.langsmith)
            from observability.langsmith import tracing_enabled

            self.assertFalse(tracing_enabled())

    def test_tracing_disabled_when_false(self):
        """When LANGSMITH_TRACING=false, tracing should be disabled."""
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "false"}):
            from observability.langsmith import tracing_enabled
            self.assertFalse(tracing_enabled())

    def test_tracing_enabled_when_true(self):
        """When LANGSMITH_TRACING=true, tracing should be enabled."""
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true"}):
            from observability.langsmith import tracing_enabled
            self.assertTrue(tracing_enabled())

    def test_tracing_enabled_case_insensitive(self):
        """LANGSMITH_TRACING should be case-insensitive."""
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "TRUE"}):
            from observability.langsmith import tracing_enabled
            self.assertTrue(tracing_enabled())

        with patch.dict(os.environ, {"LANGSMITH_TRACING": "True"}):
            from observability.langsmith import tracing_enabled
            self.assertTrue(tracing_enabled())


class TestGetRunConfig(unittest.TestCase):
    """Tests for get_run_config() function."""

    def test_run_config_contains_company_name(self):
        """Run config must contain company_name in metadata."""
        from observability.langsmith import get_run_config

        config = get_run_config("Acme Corp")

        self.assertIn("metadata", config)
        self.assertIn("company_name", config["metadata"])
        self.assertEqual(config["metadata"]["company_name"], "Acme Corp")

    def test_run_config_generates_run_id(self):
        """Run config should generate a run_id if not provided."""
        from observability.langsmith import get_run_config

        config = get_run_config("Acme Corp")

        self.assertIn("run_id", config)
        self.assertIsNotNone(config["run_id"])
        self.assertTrue(len(config["run_id"]) > 0)

    def test_run_config_uses_provided_run_id(self):
        """Run config should use provided run_id."""
        from observability.langsmith import get_run_config

        config = get_run_config("Acme Corp", run_id="custom-123")

        self.assertEqual(config["run_id"], "custom-123")

    def test_run_config_includes_extra_meta(self):
        """Run config should include extra metadata."""
        from observability.langsmith import get_run_config

        extra = {"retrieval_counts": {"profile_k": 5}}
        config = get_run_config("Acme Corp", extra_meta=extra)

        self.assertIn("retrieval_counts", config["metadata"])
        self.assertEqual(config["metadata"]["retrieval_counts"]["profile_k"], 5)

    def test_run_config_has_project_name(self):
        """Run config should include project name."""
        from observability.langsmith import get_run_config

        config = get_run_config("Acme Corp")

        self.assertIn("project_name", config)


class TestTracingContext(unittest.TestCase):
    """Tests for TracingContext class."""

    def test_context_stores_company_name(self):
        """TracingContext should store company name."""
        from observability.langsmith import TracingContext

        ctx = TracingContext(
            run_id="test-123",
            company_name="Test Company",
            time_window_days=30
        )

        self.assertEqual(ctx.company_name, "Test Company")

    def test_context_tracks_retrieval_counts(self):
        """TracingContext should track retrieval counts."""
        from observability.langsmith import TracingContext

        ctx = TracingContext(
            run_id="test-123",
            company_name="Test Company"
        )

        ctx.record_retrieval("profile", 5, ["doc1", "doc2"])
        ctx.record_retrieval("news", 10, ["doc3", "doc4"])
        ctx.record_retrieval("signals", 7, ["doc5"])

        self.assertEqual(ctx.retrieval_counts["profile_k"], 5)
        self.assertEqual(ctx.retrieval_counts["news_k"], 10)
        self.assertEqual(ctx.retrieval_counts["signals_k"], 7)

    def test_context_tracks_doc_ids(self):
        """TracingContext should track document IDs."""
        from observability.langsmith import TracingContext

        ctx = TracingContext(
            run_id="test-123",
            company_name="Test Company"
        )

        ctx.record_retrieval("profile", 2, ["doc1", "doc2"])

        self.assertEqual(ctx.retrieval_doc_ids["profile"], ["doc1", "doc2"])

    def test_context_tracks_step_timing(self):
        """TracingContext should track step timings."""
        from observability.langsmith import TracingContext

        ctx = TracingContext(
            run_id="test-123",
            company_name="Test Company"
        )

        ctx.record_step_timing("retriever", 150)
        ctx.record_step_timing("synthesizer", 2000)

        self.assertEqual(ctx.step_timings["retriever"], 150)
        self.assertEqual(ctx.step_timings["synthesizer"], 2000)

    def test_get_metadata_contains_all_fields(self):
        """get_metadata() should return all required fields."""
        from observability.langsmith import TracingContext

        ctx = TracingContext(
            run_id="test-123",
            company_name="Test Company",
            time_window_days=30
        )

        ctx.record_retrieval("profile", 5, ["doc1"])
        ctx.record_step_timing("retriever", 100)

        metadata = ctx.get_metadata()

        required_fields = [
            "company_name",
            "run_id",
            "retrieval_counts",
            "retrieval_doc_ids",
            "time_window_days",
            "step_timings_ms",
            "total_elapsed_ms",
        ]

        for field in required_fields:
            self.assertIn(field, metadata, f"Missing required field: {field}")


class TestNoLangSmithImportWhenDisabled(unittest.TestCase):
    """Test that LangSmith is not imported when tracing is disabled."""

    def test_no_langsmith_client_when_disabled(self):
        """get_langsmith_client() should return None when tracing disabled."""
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "false"}):
            from observability.langsmith import get_langsmith_client

            client = get_langsmith_client()
            self.assertIsNone(client)

    def test_trace_step_works_without_langsmith(self):
        """trace_step decorator should work when tracing disabled."""
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "false"}):
            from observability.langsmith import trace_step

            @trace_step("test_step")
            def test_function(x):
                return x * 2

            result = test_function(5)
            self.assertEqual(result, 10)

    def test_tracing_context_works_without_langsmith(self):
        """TracingContext should work when tracing disabled."""
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "false"}):
            from observability.langsmith import TracingContext

            ctx = TracingContext(
                run_id="test-123",
                company_name="Test Company"
            )

            ctx.start()
            ctx.record_retrieval("profile", 5, ["doc1"])
            ctx.end(output="test output")

            # Should not raise any errors
            metadata = ctx.get_metadata()
            self.assertIn("company_name", metadata)


class TestTraceStepDecorator(unittest.TestCase):
    """Tests for trace_step decorator."""

    def test_trace_step_preserves_function_result(self):
        """trace_step should preserve the function's return value."""
        from observability.langsmith import trace_step

        @trace_step("test_op")
        def add_numbers(a, b):
            return a + b

        result = add_numbers(3, 4)
        self.assertEqual(result, 7)

    def test_trace_step_preserves_function_name(self):
        """trace_step should preserve the function's name."""
        from observability.langsmith import trace_step

        @trace_step("test_op")
        def my_function():
            pass

        self.assertEqual(my_function.__name__, "my_function")

    def test_trace_step_handles_exceptions(self):
        """trace_step should propagate exceptions."""
        from observability.langsmith import trace_step

        @trace_step("test_op")
        def failing_function():
            raise ValueError("test error")

        with self.assertRaises(ValueError):
            failing_function()


def run_tests():
    """Run all observability tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestTracingEnabled))
    suite.addTests(loader.loadTestsFromTestCase(TestGetRunConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestTracingContext))
    suite.addTests(loader.loadTestsFromTestCase(TestNoLangSmithImportWhenDisabled))
    suite.addTests(loader.loadTestsFromTestCase(TestTraceStepDecorator))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)
