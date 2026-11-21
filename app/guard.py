"""Проверка ответа модели до отправки покупателю.

Бот не должен называть цифры, которых нет в прайсе, и давать обещания,
которых нет в правилах компании. Проверка не доверяет модели: она сверяет
каждое число в ответе с данными, которые модель получила.
"""

import re
from dataclasses import dataclass, field

# 22 000, 22000, 4 500, 1,5, 5%
NUMBER = re.compile(r"\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")

# Обещания, которые бот может давать, только если они есть в правилах
RISKY_PHRASES = (
    "гарантир",
    "бесплатн",
    "точно приед",
    "сегодня же",
    "в течение часа",
    "забронировал",
    "бронь подтвержд",
)
NEGATION = re.compile(r"\b(не|нельзя|нет|ни)\b[^.!?]{0,12}$")


def parse_numbers(text: str) -> set[float]:
    found = set()
    for raw in NUMBER.findall(text):
        cleaned = re.sub(r"[\s  ]", "", raw).replace(",", ".").rstrip(".")
        try:
            found.add(float(cleaned))
        except ValueError:
            continue
    return found


@dataclass
class GuardResult:
    unknown_numbers: list[float] = field(default_factory=list)
    risky_phrases: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unknown_numbers and not self.risky_phrases

    def explain(self) -> str:
        parts = []
        if self.unknown_numbers:
            nums = ", ".join(f"{n:g}" for n in self.unknown_numbers)
            parts.append(f"в ответе есть числа, которых нет в данных: {nums}")
        if self.risky_phrases:
            parts.append(f"в ответе есть обещания, которых нет в данных: {', '.join(self.risky_phrases)}")
        return "; ".join(parts)


def allowed_numbers(context: str, user_text: str) -> set[float]:
    """Числа, которые можно называть: из данных, из вопроса и суммы по ценам прайса."""
    base = parse_numbers(context)
    from_user = parse_numbers(user_text)
    allowed = base | from_user | {1.0, 2.0}
    # Бот может посчитать сумму: цена из прайса × число смен или часов из вопроса,
    # в том числе со скидкой 5% или 10% из правил
    prices = {n for n in base if n >= 1000}
    counts = {n for n in from_user if 1 <= n <= 60 and n == int(n)}
    for p in prices:
        for c in counts:
            for k in (1, 0.95, 0.9):
                allowed.add(round(p * c * k, 2))
    return allowed


def check(answer: str, context: str, user_text: str) -> GuardResult:
    allowed = allowed_numbers(context, user_text)
    unknown = sorted(n for n in parse_numbers(answer) if n not in allowed)
    low_answer, low_context = answer.lower(), context.lower()
    risky = []
    for phrase in RISKY_PHRASES:
        if phrase in low_context:
            continue
        for m in re.finditer(re.escape(phrase), low_answer):
            # «не гарантируем», «бронь не подтверждена» — это не обещание
            if not NEGATION.search(low_answer[max(0, m.start() - 20) : m.start()]):
                risky.append(phrase)
                break
    return GuardResult(unknown_numbers=unknown, risky_phrases=risky)
