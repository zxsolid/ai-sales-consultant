"""Прогон бота по каверзным вопросам: python -m eval.run_eval

Берёт настоящую модель из .env, задаёт каждый вопрос в новом чате
и пишет отчёт в eval/report.md.
"""

import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.agent import Consultant
from app.catalog import load_catalog
from app.llm import LLM

CASES = Path(__file__).with_name("cases.yaml")
REPORT = Path(__file__).with_name("report.md")


@dataclass
class CaseResult:
    case: dict
    answer: str
    handoff_reason: str | None
    guard_failures: list[str]
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


def check_case(case: dict, answer: str, handoff_reason: str | None) -> list[str]:
    problems = []
    for pattern in case.get("must_include", []):
        if not re.search(pattern, answer, re.IGNORECASE):
            problems.append(f"нет в ответе: {pattern}")
    for pattern in case.get("must_not_include", []):
        if re.search(pattern, answer, re.IGNORECASE):
            problems.append(f"лишнее в ответе: {pattern}")
    if "handoff" in case and bool(handoff_reason) != case["handoff"]:
        problems.append("не позвал менеджера" if case["handoff"] else "зря позвал менеджера")
    return problems


async def run(llm: LLM, cases: list[dict]) -> list[CaseResult]:
    catalog = load_catalog()
    results = []
    for case in cases:
        bot = Consultant(catalog, llm)  # новый чат на каждый вопрос
        chat = f"eval:{case['id']}"
        for previous in case.get("history", []):
            await bot.answer(chat, previous, case.get("ad"))
        reply = await bot.answer(chat, case["question"], case.get("ad"))
        result = CaseResult(case, reply.text, reply.handoff_reason, reply.guard_failures)
        result.problems = check_case(case, reply.text, reply.handoff_reason)
        results.append(result)
    return results


def render(results: list[CaseResult]) -> str:
    passed = sum(r.passed for r in results)
    caught = sum(bool(r.guard_failures) for r in results)
    lines = [
        "# Прогон по каверзным вопросам",
        "",
        f"Прошло проверок: **{passed} из {len(results)}**. "
        f"Проверка цифр поймала выдумку и заставила переписать ответ: {caught} раз.",
        "",
        "| # | Группа | Вопрос | Ответ бота | Менеджер | Итог |",
        "|---|---|---|---|---|---|",
    ]
    for n, r in enumerate(results, 1):
        answer = r.answer.replace("\n", " ").replace("|", "/")
        verdict = "✅" if r.passed else "❌ " + "; ".join(r.problems)
        if r.guard_failures:
            verdict += f" (переписан: {'; '.join(r.guard_failures)})"
        lines.append(
            f"| {n} | {r.case['group']} | {r.case['question']} | {answer} | {r.handoff_reason or '—'} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    from app.config import Settings

    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    results = await run(Settings().make_llm(), cases)
    REPORT.write_text(render(results), encoding="utf-8")
    passed = sum(r.passed for r in results)
    print(f"{passed}/{len(results)} прошло, отчёт: {REPORT}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
