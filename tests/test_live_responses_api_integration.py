from __future__ import annotations

import os
import unittest
from unittest.mock import Mock

from backend.agent.llm import (
    ResponsesAPIProbeError,
    verify_responses_api_connection,
)
from backend.config import DEFAULT_OPENAI_MODEL, env_value

try:
    from openai import APITimeoutError, AuthenticationError
except Exception:  # pragma: no cover - dependency availability varies by env
    APITimeoutError = AuthenticationError = None


class LiveResponsesAPIIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("OPENAI_API_KEY", "").strip(), "OPENAI_API_KEY not set")
    def test_live_responses_api_request_succeeds(self) -> None:
        model = env_value("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
        result = verify_responses_api_connection(
            model=model,
            api_key=os.environ["OPENAI_API_KEY"],
            timeout_seconds=10.0,
        )
        self.assertEqual(result.model, model)
        self.assertIn('"status"', result.output_text)
        self.assertTrue(result.response_id is None or isinstance(result.response_id, str))

    def test_missing_model_configuration_is_user_friendly(self) -> None:
        with self.assertRaisesRegex(ResponsesAPIProbeError, "OPENAI_MODEL must not be empty"):
            verify_responses_api_connection(model="  ", client=Mock())

    @unittest.skipIf(AuthenticationError is None, "openai package not installed")
    def test_invalid_api_key_error_is_user_friendly(self) -> None:
        fake_client = Mock()
        fake_client.responses.create.side_effect = AuthenticationError(
            message="bad key",
            response=Mock(request=Mock()),
            body=None,
        )

        with self.assertRaisesRegex(ResponsesAPIProbeError, "OpenAI authentication failed"):
            verify_responses_api_connection(model="gpt-live", client=fake_client)

    @unittest.skipIf(APITimeoutError is None, "openai package not installed")
    def test_timeout_error_is_user_friendly(self) -> None:
        fake_client = Mock()
        fake_client.responses.create.side_effect = APITimeoutError(request=Mock())

        with self.assertRaisesRegex(ResponsesAPIProbeError, "timed out"):
            verify_responses_api_connection(model="gpt-live", client=fake_client, timeout_seconds=0.01)


if __name__ == "__main__":
    unittest.main()
