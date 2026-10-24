"""LLM-as-judge for LIVE mode only.

The judge is a separate, fixed-rubric call at temperature 0. It is
never used in offline mode (there the correctness proxy is keyword
overlap, labelled as such). Judge output is parsed strictly: if the
model does not return valid JSON matching the schema, the question is
recorded with ``judge_error`` and excluded from the judged aggregate
-- a failed judge must never be counted as a pass or a fail.
"""

from __future__ import annotations

import json

import os

# When the agent runs against an OpenAI-compatible endpoint (LLM_BASE_URL
# set, e.g. Gemini), the judge must use that provider's chat model, not
# gpt-4o, or the judge call 404s on the compatible endpoint. Otherwise
# the judge stays on gpt-4o.
JUDGE_MODEL = (
    os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o")
    if os.environ.get("LLM_BASE_URL")
    else "gpt-4o"
)
JUDGE_TEMPERATURE = 0.0

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of retrieval-augmented answers. "
    "Judge ONLY against the provided source text and the expected "
    "keywords. Do not use outside knowledge. Answer ONLY with JSON."
)

JUDGE_USER_TEMPLATE = (
    "Question: {question}\n\n"
    "Expected keywords (facts the answer should contain): {keywords}\n\n"
    "Source text (the document the answer should come from):\n{source_text}\n\n"
    "Answer to judge:\n{answer}\n\n"
    "Respond with JSON exactly:\n"
    '{{"correct": true, "reason": "..."}} or '
    '{{"correct": false, "reason": "..."}}. '
    "Mark correct=true only if the answer contains the substance of "
    "the expected keywords and does not contradict the source text."
)


async def judge_answer(
    client, question: str, keywords: list[str], source_text: str, answer: str
) -> dict:
    """Run the judge; returns {correct: bool|None, reason, judge_error}."""
    try:
        response = await client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": JUDGE_USER_TEMPLATE.format(
                        question=question,
                        keywords=", ".join(keywords),
                        source_text=source_text[:4000],
                        answer=answer,
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=JUDGE_TEMPERATURE,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        if not isinstance(data.get("correct"), bool):
            raise TypeError("judge output missing boolean 'correct'")
        return {
            "correct": data["correct"],
            "reason": str(data.get("reason", ""))[:500],
            "judge_error": None,
        }
    except Exception as exc:  # noqa: BLE001 -- judge failure is recorded, not raised
        return {"correct": None, "reason": "", "judge_error": str(exc)[:300]}
