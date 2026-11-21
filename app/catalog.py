import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SHIFTS = re.compile(r"\b(\d{1,2})\s*(смен\w*|дн(?:я|ей)|день|сут\w*|shifts?|days?)", re.IGNORECASE)


LATER = re.compile(r"(через|спустя|после|in|after)\s*$", re.IGNORECASE)


def parse_shifts(text: str) -> int | None:
    """«на 5 смен», «10 дней» -> 5, 10. «Через 3 дня» — это срок, а не смены."""
    for m in SHIFTS.finditer(text):
        if not LATER.search(text[: m.start()]):
            return int(m.group(1))
    return None


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "catalog.yaml"
# Чему бот научился с одобрения менеджера: синонимы техники и ответы на частые вопросы
DEFAULT_LEARNED = DEFAULT_CATALOG.with_name("learned.yaml")


@dataclass(frozen=True)
class Item:
    id: str
    avito_item_id: int
    name: str
    price_per_shift: int
    overtime_per_hour: int
    min_shifts: int
    available: bool
    specs: str
    good_for: str
    unavailable_note: str = ""
    aliases: tuple[str, ...] = ()
    delivery: str = ""  # «своим ходом» или «тралом»

    def how_delivered(self) -> str:
        if self.delivery == "тралом":
            return "привозим тралом, трал оплачивается отдельно"
        return f"приезжает {self.delivery}" if self.delivery else ""

    def card(self) -> str:
        """Карточка машины одним текстом: её видит модель и по ней сверяются цифры."""
        status = "в наличии" if self.available else f"нет в наличии: {self.unavailable_note}"
        return (
            f"{self.name}. Цена смены {self.price_per_shift} ₽. "
            f"Переработка {self.overtime_per_hour} ₽ в час. "
            f"Минимальный заказ {self.min_shifts} смена. Статус: {status}. "
            + (f"Доставка: {self.how_delivered()}. " if self.delivery else "")
            + f"Работает с оператором, топливо входит в цену. "
            f"Характеристики: {self.specs}. Подходит для: {self.good_for}."
        )


@dataclass(frozen=True)
class Policy:
    id: str
    title: str
    text: str


@dataclass(frozen=True)
class Catalog:
    company: dict
    items: tuple[Item, ...]
    policies: tuple[Policy, ...]
    discounts: tuple[tuple[int, int], ...] = ()  # (от скольких смен, процент)

    def discount_percent(self, shifts: int) -> int:
        return max((pct for min_shifts, pct in self.discounts if shifts >= min_shifts), default=0)

    def quote(self, item: Item, shifts: int) -> str:
        """Готовый расчёт: модель называет итог отсюда, а не считает сама."""
        pct = self.discount_percent(shifts)
        total = round(item.price_per_shift * shifts * (100 - pct) / 100)
        discount = f", скидка {pct}%" if pct else ", скидки нет"
        return (
            f"Итог по прайсу: {item.name}, смен подряд: {shifts}, цена смены {item.price_per_shift} ₽"
            f"{discount}, итого {total} ₽. Доставка и переработка в итог не входят."
        )

    def by_avito_id(self, avito_item_id: int | None) -> Item | None:
        return next((i for i in self.items if i.avito_item_id == avito_item_id), None)

    def find_item(self, text: str) -> Item | None:
        """Какую машину назвал клиент: «JCB», «камаз», «мини-экскаватор»."""
        low = text.lower().replace("ё", "е")
        best: tuple[int, Item] | None = None
        for item in self.items:
            for alias in (*item.aliases, item.name.lower()):
                if alias.lower() in low and (best is None or len(alias) > best[0]):
                    best = (len(alias), item)
        return best[1] if best else None

    def items_in(self, text: str) -> list[Item]:
        """Все машины, которые упомянуты в тексте."""
        low = text.lower().replace("ё", "е")
        return [i for i in self.items if any(a.lower() in low for a in (*i.aliases, i.name.lower()))]

    def mixed_up_prices(self, answer: str) -> list[str]:
        """Цена чужой машины в предложении про одну машину: «переработка крана 2400 ₽» (2400 — у катка)."""
        from app.guard import parse_numbers

        problems = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n", answer):  # строка списка тоже отдельное предложение
            mentioned = self.items_in(sentence)
            if len(mentioned) != 1:
                continue
            own = {float(mentioned[0].price_per_shift), float(mentioned[0].overtime_per_hour)}
            others = {
                float(n) for i in self.items if i is not mentioned[0] for n in (i.price_per_shift, i.overtime_per_hour)
            }
            for n in sorted(parse_numbers(sentence) & (others - own)):
                problems.append(f"{n:g} ₽ — это цена другой машины, у «{mentioned[0].name}» другие цены")
        return problems

    def by_id(self, item_id: str) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    def price_list(self) -> str:
        """Короткий прайс: бот всегда знает, что есть в парке, а чего нет."""
        rows = [
            f"{i.name}: {money(i.price_per_shift)} ₽ за смену, переработка {money(i.overtime_per_hour)} ₽ в час"
            + (f", {i.how_delivered()}" if i.delivery else "")
            + ("" if i.available else f", сейчас нет в наличии: {i.unavailable_note}")
            for i in self.items
        ]
        return (
            "Вся техника в парке: "
            + "; ".join(rows)
            + ". Другой техники нет. В цену смены входят оператор и топливо, смена 8 часов."
        )

    def documents(self) -> list[tuple[str, str]]:
        """Все куски знаний: (id, текст). Поиск идёт по ним."""
        docs = [(f"item:{i.id}", i.card()) for i in self.items]
        docs += [(f"policy:{p.id}", f"{p.title}. {p.text}") for p in self.policies]
        c = self.company
        docs.append(("company", f"Компания {c['name']}. Регион: {c['region']}. Часы работы: {c['hours']}."))
        return docs


def load_learned(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"aliases": {}, "faq": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"aliases": data.get("aliases") or {}, "faq": data.get("faq") or []}


def load_catalog(path: Path = DEFAULT_CATALOG, learned: Path | None = None) -> Catalog:
    """learned: файл с выученным. Без него — только прайс (так работают тесты)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    extra = load_learned(learned)
    items = []
    for i in raw["items"]:
        aliases = [*i.get("aliases", ()), *extra["aliases"].get(i["id"], [])]
        items.append(Item(**{**i, "aliases": tuple(dict.fromkeys(aliases))}))
    policies = [Policy(**p) for p in raw["policies"]]
    policies += [Policy(f"faq-{n}", f["question"], f["answer"]) for n, f in enumerate(extra["faq"], 1)]
    return Catalog(
        company=raw["company"],
        items=tuple(items),
        policies=tuple(policies),
        discounts=tuple((d["min_shifts"], d["percent"]) for d in raw.get("discounts", [])),
    )
