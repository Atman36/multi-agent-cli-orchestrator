from __future__ import annotations

import os
import unittest

from orchestrator.log_sanitizer import redact


class LogSanitizerTests(unittest.TestCase):
    def test_redacts_anthropic_key_pattern(self) -> None:
        text = "token=sk-ant-ABCdef1234567890_xyzXYZ9876543210"
        redacted = redact(text)
        self.assertIn("[REDACTED:anthropic_key]", redacted)
        self.assertNotIn("sk-ant-", redacted)

    def test_redacts_openai_key_pattern(self) -> None:
        text = "token=sk-abcdefghijklmnopqrstuvwxyz123456"
        redacted = redact(text)
        self.assertIn("[REDACTED:openai_key]", redacted)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", redacted)

    def test_redacts_sensitive_env_var_values(self) -> None:
        os.environ["TEST_SECRET_TOKEN"] = "my-very-secret-value"
        try:
            text = "env leak: my-very-secret-value"
            redacted = redact(text, sensitive_env_vars=["TEST_SECRET_TOKEN"])
            self.assertEqual(redacted, "env leak: [REDACTED:env:TEST_SECRET_TOKEN]")
        finally:
            os.environ.pop("TEST_SECRET_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
