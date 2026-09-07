import os
import sys
import types
import unittest
from unittest import mock

from services.llm_service import active_provider, answer_financial_question_from_audio, explain_financial_result


class TestLlmProviderSelection(unittest.TestCase):
    def setUp(self):
        # Isolate from whatever is actually set in this environment.
        self._env_patcher = mock.patch.dict(
            os.environ,
            {k: v for k, v in os.environ.items()
             if k not in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "NYASHA_DEMO_MODE")},
            clear=True,
        )
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()

    def test_no_keys_means_demo_mode(self):
        self.assertIsNone(active_provider())

    def test_anthropic_key_selects_anthropic(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        self.assertEqual(active_provider(), "anthropic")

    def test_gemini_key_selects_gemini(self):
        os.environ["GEMINI_API_KEY"] = "test-key"
        self.assertEqual(active_provider(), "gemini")

    def test_google_api_key_also_selects_gemini(self):
        os.environ["GOOGLE_API_KEY"] = "test-key"
        self.assertEqual(active_provider(), "gemini")

    def test_anthropic_wins_when_both_keys_present(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        os.environ["GEMINI_API_KEY"] = "test-key"
        self.assertEqual(active_provider(), "anthropic")

    def test_demo_mode_flag_overrides_any_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        os.environ["NYASHA_DEMO_MODE"] = "true"
        self.assertIsNone(active_provider())

    def test_no_key_produces_labeled_demo_response_not_a_crash(self):
        result = explain_financial_result({"revenue": 100})
        self.assertIn("DEMO MODE", result)

    def test_gemini_key_without_sdk_installed_falls_back_to_demo(self):
        # google-genai is not installed in this sandbox -- confirms the
        # ImportError path degrades to the labeled demo response too.
        os.environ["GEMINI_API_KEY"] = "test-key"
        result = explain_financial_result({"revenue": 100})
        self.assertIn("DEMO MODE", result)
        self.assertIn("google-genai", result)

    def test_provider_sdk_exception_degrades_gracefully_not_a_crash(self):
        # Regression test: a live deployment hit google.genai.errors.ClientError
        # (a 404 for an outdated model name) which was NOT a RuntimeError, so
        # the old `except RuntimeError` in explain_financial_result let it
        # propagate and crash the whole Streamlit page instead of falling
        # back to demo mode. Any exception from either provider's SDK must
        # degrade to the labeled demo response instead.
        os.environ["GEMINI_API_KEY"] = "test-key"

        class FakeProviderError(Exception):
            pass

        with mock.patch("services.llm_service._call_gemini", side_effect=FakeProviderError("404 NOT_FOUND")):
            result = explain_financial_result({"revenue": 100})
        self.assertIn("DEMO MODE", result)
        self.assertIn("FakeProviderError", result)
        self.assertIn("404 NOT_FOUND", result)


class TestVoiceQuestions(unittest.TestCase):
    """answer_financial_question_from_audio always routes to Gemini -- Claude's
    API doesn't accept audio input -- regardless of active_provider()."""

    def setUp(self):
        self._env_patcher = mock.patch.dict(
            os.environ,
            {k: v for k, v in os.environ.items()
             if k not in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "NYASHA_DEMO_MODE")},
            clear=True,
        )
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()

    def test_no_gemini_sdk_installed_falls_back_to_demo(self):
        # google-genai is not installed in this sandbox.
        os.environ["GEMINI_API_KEY"] = "test-key"
        result = answer_financial_question_from_audio(b"fake-audio", "audio/wav", {"revenue": 100})
        self.assertIn("DEMO MODE", result)
        self.assertIn("google-genai", result)

    def test_anthropic_key_alone_is_not_enough_for_voice(self):
        # Regression guard: voice must not silently try (and fail oddly
        # inside) Anthropic just because active_provider() would normally
        # pick it for text questions -- it should clearly say a Gemini key
        # is needed, even though an Anthropic key is present and valid for
        # ordinary text questions.
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        fake_genai = types.ModuleType("google.genai")
        fake_genai.types = types.SimpleNamespace(Part=types.SimpleNamespace(from_bytes=lambda **k: None))
        fake_genai.Client = lambda **k: None
        fake_google = types.ModuleType("google")
        fake_google.genai = fake_genai
        with mock.patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            result = answer_financial_question_from_audio(b"fake-audio", "audio/wav", {"revenue": 100})
        self.assertIn("DEMO MODE", result)
        self.assertIn("Gemini API key", result)


if __name__ == "__main__":
    unittest.main()
