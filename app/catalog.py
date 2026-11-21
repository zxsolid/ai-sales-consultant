from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "catalog.yaml"


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

    def card(self) -> str:
        """Карточка машины одним текстом: её видит модель и по ней сверяются цифры."""
        status = "в наличии" if self.available else f"нет в наличии: {self.unavailable_note}"
        return (
            f"{self.name}. Цена смены {self.price_per_shift} ₽. "
            f"Переработка {self.overtime_per_hour} ₽ в час. "
            f"Минимальный заказ {self.min_shifts} смена. Статус: {status}. "
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

    def by_avito_id(self, avito_item_id: int | None) -> Item | None:
        return next((i for i in self.items if i.avito_item_id == avito_item_id), None)

    def by_id(self, item_id: str) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    def price_list(self) -> str:
        """Короткий прайс: бот всегда знает, что есть в парке, а чего нет."""
        rows = [
            f"{i.name}: {i.price_per_shift} ₽ за смену" + ("" if i.available else " (сейчас нет в наличии)")
            for i in self.items
        ]
        return "Вся техника в парке: " + "; ".join(rows) + ". Другой техники нет."

    def documents(self) -> list[tuple[str, str]]:
        """Все куски знаний: (id, текст). Поиск идёт по ним."""
        docs = [(f"item:{i.id}", i.card()) for i in self.items]
        docs += [(f"policy:{p.id}", f"{p.title}. {p.text}") for p in self.policies]
        c = self.company
        docs.append(("company", f"Компания {c['name']}. Регион: {c['region']}. Часы работы: {c['hours']}."))
        return docs


def load_catalog(path: Path = DEFAULT_CATALOG) -> Catalog:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Catalog(
        company=raw["company"],
        items=tuple(Item(**i) for i in raw["items"]),
        policies=tuple(Policy(**p) for p in raw["policies"]),
    )
