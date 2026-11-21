from pathlib import Path

import yaml

from eval.run_eval import check_case, render, run

CASES = yaml.safe_load((Path(__file__).parent.parent / "eval" / "cases.yaml").read_text(encoding="utf-8"))


def test_cases_file_is_valid():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) >= 30
    for c in CASES:
        assert c["question"] and c["group"]


def test_check_case_reports_problems():
    case = {"must_include": [r"22\s?000"], "must_not_include": ["забронировал"], "handoff": True}
    assert check_case(case, "Смена 22 000 ₽.", "готов заказать") == []
    problems = check_case(case, "Смена 25 000 ₽, забронировал.", None)
    assert problems == [r"нет в ответе: 22\s?000", "лишнее в ответе: забронировал", "не позвал менеджера"]


async def test_run_and_report_with_scripted_model():
    from app.llm import ScriptedLLM

    cases = [
        {"id": "a", "group": "цены", "question": "Почём кран?", "must_include": [r"32\s?000"]},
        {"id": "b", "group": "цены", "question": "Почём камаз?", "must_include": [r"16\s?000"]},
    ]
    llm = ScriptedLLM(lambda m: "Смена 32 000 ₽.")
    results = await run(llm, cases)
    assert [r.passed for r in results] == [True, False]
    report = render(results)
    assert "Прошло проверок: **1 из 2**" in report
    assert "❌ нет в ответе" in report
