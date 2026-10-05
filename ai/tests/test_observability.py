"""Unit tests for the tracing layer.

These assert the no-op contract: with the OpenTelemetry SDK absent the service
must still run and still report timing, so tracing can never be the reason a
deployment fails to start.
"""

from __future__ import annotations

import pytest

from observability import OTEL_AVAILABLE, configure, genai_attributes, span


class TestConfigure:
    def test_returns_a_bool_and_never_raises(self) -> None:
        assert isinstance(configure("test-service", "0.0.1"), bool)

    def test_available_flag_is_a_bool(self) -> None:
        assert isinstance(OTEL_AVAILABLE, bool)


class TestSpan:
    def test_records_a_duration(self) -> None:
        with span("unit") as record:
            pass
        assert record.duration_ms >= 0.0

    def test_passes_attributes_through(self) -> None:
        with span("unit", node="draft_sql") as record:
            assert record.attributes["node"] == "draft_sql"

    def test_caller_can_attach_attributes_inside_the_block(self) -> None:
        with span("unit") as record:
            record.attributes["attempt"] = 2
        assert record.attributes["attempt"] == 2

    def test_captures_the_error_and_reraises(self) -> None:
        with pytest.raises(ValueError), span("unit") as record:
            raise ValueError("boom")
        assert record.error == "ValueError: boom"

    def test_no_error_by_default(self) -> None:
        with span("unit") as record:
            pass
        assert record.error is None


class TestGenAiAttributes:
    def test_uses_the_semantic_convention_names(self) -> None:
        attrs = genai_attributes("gpt-4o", prompt_tokens=10, completion_tokens=5)
        assert attrs["gen_ai.system"] == "openai-compatible"
        assert attrs["gen_ai.operation.name"] == "chat"
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        assert attrs["gen_ai.usage.input_tokens"] == 10
        assert attrs["gen_ai.usage.output_tokens"] == 5

    def test_operation_is_overridable(self) -> None:
        assert genai_attributes("m", operation="retrieve")["gen_ai.operation.name"] == "retrieve"
