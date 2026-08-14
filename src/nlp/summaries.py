"""Grounded LLM summary — structured grounding, NOT RAG.

The evidence is a small, known set of computed numbers, so there is nothing to
retrieve. Every number-bearing claim (significance, trend, the lag verdict) is
decided in Python and passed in as fixed `facts`. The model only weaves narrative
around them and must never emit a statistic of its own.

Contract returned to the caller (always this shape, even without a key):
    {summary: str, caveats: [str], cited_headline_ids: [int], abstained: bool,
     grounded: bool}   # grounded=True only when a validated LLM response was used

Validation: every cited id must exist in the payload, and every numeric token in
the model's summary must appear in the deterministic facts — on any drift we fall
back to the deterministic fact sentences. summarize() never raises.
"""
from __future__ import annotations

import json
import re

from src.settings import env

SYSTEM_PROMPT = (
    "You are an evidence-bound analyst for a news-sentiment observatory. You are "
    "given (a) a JSON evidence payload and (b) a list of already-decided factual "
    "sentences. Write a short, neutral narrative that ONLY restates and connects "
    "those facts. Rules: do NOT introduce any number, statistic, correlation, or "
    "percentage that is not already in the facts. Do NOT assert causation. Cite "
    "supporting headlines by their integer id in `cited_headline_ids`. If the facts "
    "say the sample is too small, set abstained=true and keep the summary cautious. "
    "Respond ONLY as JSON: "
    '{"summary": str, "caveats": [str], "cited_headline_ids": [int], "abstained": bool}'
)

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[str]:
    return {m.group().lstrip("-") for m in _NUM.finditer(text or "")}


def _allowed_numbers(facts: list[str], evidence: dict) -> set[str]:
    allowed: set[str] = set()
    for f in facts:
        allowed |= _numbers_in(f)
    allowed |= _numbers_in(json.dumps(evidence))
    # tolerate integer-vs-float renderings of the same value (e.g. 2 vs 2.0)
    for n in list(allowed):
        if n.endswith(".0"):
            allowed.add(n[:-2])
        allowed.add(n.split(".")[0])
    return allowed


def _fallback(facts: list[str], abstained: bool) -> dict:
    return {
        "summary": " ".join(facts) if facts else "Insufficient evidence to summarize.",
        "caveats": ["Deterministic summary (LLM disabled or its output failed validation)."],
        "cited_headline_ids": [],
        "abstained": abstained,
        "grounded": False,
    }


def summarize(evidence: dict, facts: list[str], abstained: bool = False) -> dict:
    """Return the grounded-summary contract. Never raises."""
    api_key = env("GROQ_API_KEY")
    if not api_key or not facts:
        return _fallback(facts, abstained)

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        model = env("GROQ_MODEL", "llama-3.3-70b-versatile")
        user = (
            "EVIDENCE (JSON):\n" + json.dumps(evidence, ensure_ascii=False)
            + "\n\nFACTS (already decided — restate only these; add no new numbers):\n"
            + "\n".join(f"- {f}" for f in facts)
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception:
        return _fallback(facts, abstained)

    # ── post-validation with fallback ────────────────────────────────────────
    valid_ids = {h.get("id") for h in evidence.get("headlines", [])}
    cited = [i for i in data.get("cited_headline_ids", []) if i in valid_ids]
    if len(cited) != len(data.get("cited_headline_ids", [])):
        return _fallback(facts, abstained)  # hallucinated a citation

    allowed = _allowed_numbers(facts, evidence)
    if not _numbers_in(data.get("summary", "")).issubset(allowed):
        return _fallback(facts, abstained)  # emitted an unsupported number

    return {
        "summary": data.get("summary", ""),
        "caveats": list(data.get("caveats", [])),
        "cited_headline_ids": cited,
        "abstained": bool(data.get("abstained", abstained)),
        "grounded": True,
    }
