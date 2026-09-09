"""LLM-judge for root-cause accuracy. A single isolated, tool-free `claude`
call comparing the investigation's own conclusion against the scenario's
known-correct root cause — cheap (no tools, no investigation, just two
paragraphs of text) relative to the investigation itself.

This is deliberately a separate, narrower call rather than reusing the
investigation's own session: judging "did you get it right" from inside the
same context that produced the answer would be grading your own homework.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.orchestrator.cli_agent import ClaudeCliError, run_isolated_json

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {
            "type": "boolean",
            "description": "True if the candidate conclusion identifies the same root cause "
            "as the reference, even if worded differently. False if it names a different "
            "cause, hedges without committing, or is materially incomplete.",
        },
        "explanation": {"type": "string"},
    },
    "required": ["correct", "explanation"],
}


@dataclass
class JudgeResult:
    correct: bool
    explanation: str
    cost_usd: float


async def judge_root_cause(
    *, reference_root_cause: str, candidate_tldr: str, candidate_reasoning: str, timeout_s: int
) -> JudgeResult:
    prompt = f"""You are grading whether an AI SRE's investigation correctly identified the
root cause of an incident. Compare the CANDIDATE conclusion against the REFERENCE (known
ground truth). Judge substance, not wording — they don't need to match verbatim.

REFERENCE root cause:
{reference_root_cause}

CANDIDATE conclusion (TL;DR):
{candidate_tldr}

CANDIDATE reasoning:
{candidate_reasoning}

Does the candidate correctly identify the same root cause as the reference?"""

    try:
        result = await run_isolated_json(
            prompt=prompt, json_schema=_JUDGE_SCHEMA, timeout_s=timeout_s
        )
    except ClaudeCliError as e:
        return JudgeResult(correct=False, explanation=f"Judge call failed: {e}", cost_usd=0.0)

    return JudgeResult(
        correct=bool(result.structured_output.get("correct", False)),
        explanation=result.structured_output.get("explanation", ""),
        cost_usd=result.total_cost_usd,
    )
