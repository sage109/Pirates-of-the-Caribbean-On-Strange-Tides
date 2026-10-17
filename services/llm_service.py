"""
services/llm_service.py

Section 17 & 37 (STRICT): the LLM must NEVER calculate financial figures.
Every function in this module takes already-computed, verified numbers as
input and asks the LLM only to explain, summarise, or recommend based on
them. If you catch yourself wanting the LLM to "figure out the total" or
"estimate the margin" -- stop, that belongs in analytics/, not here.

Supports two providers, picked automatically based on which key is set
(Anthropic takes priority if both happen to be set):
  - Anthropic:  set ANTHROPIC_API_KEY   (see .env.example)
  - Gemini:     set GEMINI_API_KEY (or GOOGLE_API_KEY)

This module has NOT been exercised against either live API in this sandbox
(no network) -- the prompt construction and verified-data-injection pattern
are ready to go, but test the actual API call in a networked environment
before the demo.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any

ANTHROPIC_MODEL = "claude-sonnet-4-6"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
# Raised from 800: a thorough breakdown (e.g. a numbered list of profitability
# components) can genuinely need more room, and a response cut off mid-list
# looks identical to the '$' rendering bug this module also fixes -- don't
# let this be a second source of the same "answer looks incomplete" symptom.
MAX_OUTPUT_TOKENS = int(os.environ.get("NYASHA_LLM_MAX_TOKENS", "1500"))

SYSTEM_PROMPT = """You are the explanation and recommendation layer of Sarudzo AI, \
a financial decision-support tool for Zimbabwean SMEs. You will be given VERIFIED \
financial figures that have already been calculated by deterministic Python code. \

Rules you must follow:
1. NEVER invent, estimate, or recalculate a number about THIS business. Any figure \
you state about this specific business's finances must come from the verified data \
you were given.
2. You may answer general financial, accounting, tax, or business-management \
questions using your own knowledge -- e.g. explaining what a financial term means, \
how a ratio is typically interpreted, general Zimbabwean VAT rules, or general \
advice on improving cash flow or profitability. This general knowledge does not \
need to come from the verified data.
3. If a question asks for a specific number or fact about THIS business that isn't \
in the verified data you were given, say: "I cannot determine this from the \
available transaction data." Do not guess or estimate a business-specific figure.
4. Keep explanations short and plain-language. When discussing this business's own \
numbers, tie them to the specific figures provided; general knowledge answers don't \
need to reference this business's data.
5. Never claim a transaction is fraudulent -- use "unusual", "potential anomaly", or \
"requires review" only.
6. Always tie recommendations about this business back to the specific figures that \
motivate them.
7. If asked to respond in a language other than English, respond fully in that \
language, including all figures with their original values unchanged.
8. Always note that you are a decision-support tool, not a replacement for \
professional tax or accounting advice, when discussing VAT or tax matters."""


def _serialise(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialise(v) for v in obj]
    return obj


def active_provider() -> str | None:
    """Returns 'anthropic', 'gemini', or None (demo mode) -- based purely
    on which key is present in the environment. Anthropic wins if both are
    set, since it's this project's original/primary integration.
    NYASHA_DEMO_MODE=true forces demo mode even with a key present
    (useful for a rehearsal where you don't want to burn API calls)."""
    if os.environ.get("NYASHA_DEMO_MODE", "").strip().lower() in ("1", "true", "yes"):
        return None
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return None


def _call_anthropic(user_prompt: str) -> str:
    try:
        import anthropic  # imported lazily -- not required for the rest of the app to load
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        ) from exc

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _call_gemini(user_prompt: str) -> str:
    try:
        from google import genai  # google-genai SDK, imported lazily
    except ImportError as exc:
        raise RuntimeError(
            "The 'google-genai' package is not installed. Run: pip install google-genai"
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config={"system_instruction": SYSTEM_PROMPT, "max_output_tokens": MAX_OUTPUT_TOKENS},
    )
    return response.text


def _call_llm(user_prompt: str) -> str:
    """
    Provider-agnostic entry point. Isolated in its own function so it's the
    only place that needs changing if the SDK/model/provider changes, and
    so it can be mocked in tests without touching prompt-construction logic.
    """
    provider = active_provider()
    if provider == "anthropic":
        return _call_anthropic(user_prompt)
    if provider == "gemini":
        return _call_gemini(user_prompt)
    raise RuntimeError(
        "No LLM API key is set. Set ANTHROPIC_API_KEY or GEMINI_API_KEY "
        "(copy .env.example to .env and add one), or use demo/mock mode (Section 35)."
    )


def _mock_response(reason: str) -> str:
    """Section 35: offline/demo fallback -- clearly labeled, never pretending to be a real AI response."""
    return (
        f"[DEMO MODE -- mock AI response, {reason}]\n\n"
        "The verified figures above show the business's current position. "
        "Connect a live LLM API key to get a full narrative explanation and recommendations here."
    )


def _describe_error(exc: Exception) -> str:
    """
    Turns any exception from either provider's SDK into a short, readable
    reason string for _mock_response -- never a raw stack trace in the UI.
    Deliberately broad (catches Exception, not just RuntimeError) because a
    provider outage, bad model name, rate limit, or invalid key should
    degrade to demo mode, not crash the whole Streamlit page -- this is
    exactly the gap a live 404 from Gemini exposed during testing.
    """
    message = str(exc)
    if len(message) > 300:
        message = message[:300] + "..."
    return f"{type(exc).__name__}: {message}"


def _safe_call_llm(prompt: str) -> str:
    try:
        return _call_llm(prompt)
    except Exception as e:  # noqa: BLE001 -- intentionally broad, see _describe_error docstring
        return _mock_response(_describe_error(e))


def _call_gemini_with_audio(audio_bytes: bytes, mime_type: str, prompt_text: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "The 'google-genai' package is not installed. Run: pip install google-genai"
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Voice questions need a Gemini API key (GEMINI_API_KEY or GOOGLE_API_KEY) -- "
            "Claude's API doesn't accept audio input yet. Type the question instead, or add a Gemini key."
        )

    client = genai.Client(api_key=api_key)
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt_text, audio_part],
        config={"system_instruction": SYSTEM_PROMPT, "max_output_tokens": MAX_OUTPUT_TOKENS},
    )
    return response.text


def answer_financial_question_from_audio(
    audio_bytes: bytes, mime_type: str, verified_context: dict[str, Any], language: str = "en",
) -> str:
    """
    Voice variant of answer_financial_question. Always routes to Gemini,
    bypassing active_provider()'s normal Anthropic-first selection --
    Claude's Messages API doesn't currently accept raw audio input (confirmed
    against Anthropic's public SDK feature-request tracker as of this
    writing; text and images only), while Gemini's generate_content natively
    accepts inline audio alongside a text prompt in one call. If only
    ANTHROPIC_API_KEY is set (no Gemini key), this degrades to the same
    labeled demo-mode response as any other unavailable-provider case,
    explaining that voice input specifically needs a Gemini key.
    Untested against the live API in this sandbox (no network) -- same
    caveat as the rest of this module.
    """
    payload = json.dumps(_serialise(verified_context), indent=2, default=str)
    prompt_text = (
        f"Language for your response: {language}\n\n"
        f"Verified financial data available to you about this business:\n{payload}\n\n"
        "The user's question is in the attached audio clip. First work out what they're "
        "asking. If it's about this business specifically, answer using only the verified "
        "data above -- if it doesn't contain what's needed, say so explicitly rather than "
        "guessing. If it's a general financial, accounting, tax, or business-management "
        "question, you may answer it using your own knowledge."
    )
    try:
        return _call_gemini_with_audio(audio_bytes, mime_type, prompt_text)
    except Exception as e:  # noqa: BLE001 -- same broad-catch rationale as _safe_call_llm
        return _mock_response(_describe_error(e))


def explain_financial_result(verified_data: dict[str, Any], language: str = "en") -> str:
    """
    General-purpose explainer: hands the LLM a dict of already-computed
    figures (e.g. from ProfitabilitySummary, FinancialHealthScore, etc.)
    and asks for a short management-style explanation.
    """
    payload = json.dumps(_serialise(verified_data), indent=2, default=str)
    prompt = (
        f"Language for your response: {language}\n\n"
        f"Verified financial data (already calculated -- do not recalculate anything):\n{payload}\n\n"
        "Provide: (1) a one-paragraph plain-language summary of what this means, "
        "(2) up to 3 main concerns if any, (3) up to 3 recommended management actions, "
        "each explicitly tied to a figure above."
    )
    return _safe_call_llm(prompt)


def answer_financial_question(question: str, verified_context: dict[str, Any], language: str = "en") -> str:
    """
    AI Financial Assistant (Section 19). `verified_context` should contain
    everything the assistant is allowed to reason over for this business --
    e.g. the current health score, profitability summary, top anomalies,
    forecast, etc. The assistant can also answer general financial/business
    questions using its own knowledge (see SYSTEM_PROMPT); it only refuses
    when asked for a business-specific figure that isn't in verified_context.
    """
    payload = json.dumps(_serialise(verified_context), indent=2, default=str)
    prompt = (
        f"Language for your response: {language}\n\n"
        f"Verified financial data available to you about this business:\n{payload}\n\n"
        f"User question: {question}\n\n"
        "If this question is about this business specifically, answer using only the "
        "verified data above -- if it doesn't contain what's needed, say so explicitly "
        "rather than guessing. If this is a general financial, accounting, tax, or "
        "business-management question, you may answer it using your own knowledge."
    )
    return _safe_call_llm(prompt)
