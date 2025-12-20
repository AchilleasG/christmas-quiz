import asyncio
import os
from typing import Optional

import httpx
import logging

logger = logging.getLogger("ai_evaluator")
if logger.level == logging.NOTSET:
    logger.setLevel(logging.INFO)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "5"))


async def evaluate_text_answer(
    user_answer: Optional[str], target_answer: Optional[str]
) -> bool:
    """Return True if the user's answer is acceptable compared to the target."""
    if not user_answer or not target_answer:
        return False
    # Fallback simple check if no API key
    if not OPENAI_API_KEY:
        return user_answer.strip().lower() == target_answer.strip().lower()

    prompt = (
        "You are grading a quiz answer. Decide ONLY true/false if the user's answer is acceptable. "
        "Accept reasonable variants, pluralization, small typos, or added 'the', 'a', punctuation."
        "Also potentially the user might respond in English or Greek, both should be deemed correct if the answer is correct."
        "Some answers might be loose translations of the target. Always prefer to grant the point if unsure\n"
        "Be lenient and judge like a generous host.\n\n"
        f"Target: {target_answer}\n"
        f"User: {user_answer}\n"
        "Return a single word: true or false."
    )

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "You grade quiz answers as true/false only."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 3,
    }

    try:
        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        if resp.status_code != 200:
            logger.warning(
                "AI eval failed status: %s body: %s", resp.status_code, resp.text
            )
            return user_answer.strip().lower() == target_answer.strip().lower()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip().lower()
        verdict = content.startswith("true")
        logger.info(
            "AI eval: user=%r target=%r model=%s verdict=%s raw=%r",
            user_answer,
            target_answer,
            OPENAI_MODEL,
            verdict,
            content,
        )
        return verdict
    except Exception as exc:
        logger.error(
            "AI eval exception for answer=%r target=%r: %s",
            user_answer,
            target_answer,
            exc,
        )
        return user_answer.strip().lower() == target_answer.strip().lower()
