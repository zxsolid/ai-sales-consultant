"""Бот учится на клиентах, но только с одобрения менеджера.

Бот замечает, что клиент назвал технику незнакомым словом или спросил то,
чего нет в прайсе, и предлагает менеджеру правку. Менеджер нажимает кнопку
или пишет ответ, правка ложится в data/learned.yaml, и бот сразу её использует.
Сам бот ничего не запоминает: иначе он мог бы выучить ошибку и повторять её всем.
"""

import itertools
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.catalog import DEFAULT_LEARNED, Catalog, load_learned

log = logging.getLogger("learning")


@dataclass
class Suggestion:
    id: str
    kind: str  # alias — новое слово для машины, answer — ответ на вопрос, которого нет в прайсе
    text: str  # что показать менеджеру
    word: str = ""
    item_id: str = ""
    item_name: str = ""
    question: str = ""


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-zа-яё0-9]+", text.lower().replace("ё", "е")))


class Learner:
    def __init__(self, path: Path = DEFAULT_LEARNED, on_change: Callable[[], None] | None = None):
        self.path = path
        self.on_change = on_change
        self.pending: dict[str, Suggestion] = {}
        self._asked: set[str] = set()  # не предлагать одно и то же дважды, даже после «Нет»
        self._ids = itertools.count(1)

    def notice(self, catalog: Catalog, text: str, reply) -> Suggestion | None:
        """Есть ли в этом сообщении клиента чему поучиться. reply — ответ консультанта."""
        word = (reply.machine_word or "").strip()
        item = catalog.find_item(reply.model_item or "")
        if word and item and 2 <= len(word) <= 30 and catalog.find_item(word) is None:
            key = f"alias:{item.id}:{_norm(word)}"
            if key not in self._asked:
                return self._add(
                    key,
                    Suggestion(
                        "",
                        "alias",
                        f"🧠 Клиент назвал технику «{word}». Похоже, это {item.name}. Запомнить это слово?",
                        word=word.lower(),
                        item_id=item.id,
                        item_name=item.name,
                    ),
                )
        if reply.unanswered and len(text) <= 300:
            key = f"answer:{_norm(text)}"
            if key not in self._asked:
                return self._add(
                    key,
                    Suggestion(
                        "",
                        "answer",
                        f"🧠 В прайсе нет ответа на вопрос клиента: «{text}». "
                        "Напишите ответ, и бот будет отвечать так всем.",
                        question=text,
                    ),
                )
        return None

    def _add(self, key: str, s: Suggestion) -> Suggestion:
        self._asked.add(key)
        s.id = str(next(self._ids))
        self.pending[s.id] = s
        return s

    def reject(self, sid: str) -> str:
        self.pending.pop(sid, None)
        return "Хорошо, не запоминаю."

    def accept(self, sid: str, answer: str | None = None) -> str:
        s = self.pending.pop(sid, None)
        if s is None:
            return "Это предложение уже обработано."
        data = load_learned(self.path)
        if s.kind == "alias":
            words = data["aliases"].setdefault(s.item_id, [])
            if s.word not in words:
                words.append(s.word)
            done = f"Запомнил: «{s.word}» значит {s.item_name}."
        else:
            if not answer or not answer.strip():
                self.pending[s.id] = s
                return "Ответ пустой. Напишите его текстом."
            data["faq"].append({"question": s.question, "answer": answer.strip()})
            done = f"Запомнил. На вопрос «{s.question}» бот теперь отвечает: {answer.strip()}"
        self.path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        log.info("Выучено: %s", done)
        if self.on_change:
            self.on_change()
        return done
