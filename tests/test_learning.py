import json

import pytest

from app.agent import Consultant, Reply
from app.catalog import load_catalog
from app.learning import Learner
from app.llm import ScriptedLLM


@pytest.fixture
def learned(tmp_path):
    return tmp_path / "learned.yaml"


def test_new_word_for_machine_is_suggested_and_learned(learned):
    catalog = load_catalog(learned=learned)
    assert catalog.find_item("нужна копалка") is None
    learner = Learner(learned)
    s = learner.notice(catalog, "нужна копалка", Reply("", machine_word="копалка", model_item="Kubota U27"))
    assert s.text == "🧠 Клиент назвал технику «копалка». Похоже, это Мини-экскаватор Kubota U27. Запомнить это слово?"
    assert learner.accept(s.id) == "Запомнил: «копалка» значит Мини-экскаватор Kubota U27."
    assert load_catalog(learned=learned).find_item("нужна копалка").id == "kubota-u27"


def test_known_word_and_repeat_are_not_suggested(learned):
    catalog, learner = load_catalog(), Learner(learned)
    assert learner.notice(catalog, "кран", Reply("", machine_word="кран", model_item="Автокран")) is None
    s = learner.notice(catalog, "копалка", Reply("", machine_word="копалка", model_item="Kubota"))
    learner.reject(s.id)
    assert learner.notice(catalog, "копалка", Reply("", machine_word="копалка", model_item="Kubota")) is None


def test_word_for_machine_we_dont_have_is_not_suggested(learned):
    reply = Reply("", machine_word="бульдозер", model_item="бульдозер")
    assert Learner(learned).notice(load_catalog(), "бульдозер есть?", reply) is None


def test_manager_answer_becomes_part_of_price_list(learned):
    learner = Learner(learned)
    s = learner.notice(load_catalog(), "Работаете в выходные?", Reply("", unanswered=True))
    assert s.kind == "answer"
    assert learner.accept(s.id, "  ") == "Ответ пустой. Напишите его текстом."
    done = learner.accept(s.id, "Да, в субботу и воскресенье с 8:00 до 20:00.")
    assert done.startswith("Запомнил. На вопрос «Работаете в выходные?»")
    policies = load_catalog(learned=learned).policies
    assert policies[-1].title == "Работаете в выходные?"


async def test_bot_answers_with_learned_answer(learned):
    learner = Learner(learned)
    s = learner.notice(load_catalog(), "Работаете в выходные?", Reply("", unanswered=True))
    llm = ScriptedLLM(
        lambda m: json.dumps({"intent": "question", "order": {}, "reply": "Да, в выходные с 8:00 до 20:00."})
    )
    bot = Consultant(load_catalog(), llm)
    learner.on_change = lambda: bot.reload(load_catalog(learned=learned))
    learner.accept(s.id, "Да, в субботу и воскресенье с 8:00 до 20:00.")
    r = await bot.answer("c1", "Вы в выходные работаете?")
    assert "в субботу и воскресенье" in llm.calls[0][0]["content"]
    assert r.guard_failures == []


async def test_dialog_reports_what_to_learn():
    answer = {
        "intent": "question",
        "order": {"item": "Kubota U27"},
        "machine_word": "копалка",
        "need_manager": False,
        "reply": "Kubota U27: 18 000 ₽ за смену.",
    }
    r = await Consultant(load_catalog(), ScriptedLLM(lambda m: json.dumps(answer))).answer("c1", "почём копалка?")
    assert r.machine_word == "копалка" and r.model_item == "Kubota U27" and not r.unanswered
