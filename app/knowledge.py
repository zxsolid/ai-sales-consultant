import re

from rank_bm25 import BM25Okapi

from app.catalog import Catalog

WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

# Как покупатели называют технику в чатах -> слова из прайса
SYNONYMS = {
    "кран": "автокран",
    "автокран": "кран",
    "экскаватор": "экскаватор-погрузчик мини-экскаватор",
    "трактор": "экскаватор-погрузчик",
    "погрузчик": "экскаватор-погрузчик",
    "мини": "мини-экскаватор",
    "камаз": "самосвал",
    "самосвал": "камаз",
    "каток": "bomag",
    "доставка": "трал",
    "привезти": "трал доставка",
    "скидка": "скидки",
    "дешевле": "скидки",
    "оплата": "счёт предоплата",
    "отмена": "отменить",
}


def _stem(word: str) -> str:
    # Грубая обрезка окончаний: «экскаватора» и «экскаватор» дают один корень
    return word[:6] if len(word) > 6 else word


def tokenize(text: str) -> list[str]:
    words = [w.lower().replace("ё", "е") for w in WORD.findall(text)]
    expanded = list(words)
    for w in words:
        expanded += WORD.findall(SYNONYMS.get(w, ""))
    return [_stem(w) for w in expanded]


class Knowledge:
    """Поиск по прайсу и правилам компании (BM25)."""

    def __init__(self, catalog: Catalog):
        self.docs = catalog.documents()
        self._bm25 = BM25Okapi([tokenize(text) for _, text in self.docs])

    def search(self, query: str, k: int = 4) -> list[tuple[str, str]]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(scores, self.docs, strict=True), key=lambda x: -x[0])
        return [doc for score, doc in ranked[:k] if score > 0]
