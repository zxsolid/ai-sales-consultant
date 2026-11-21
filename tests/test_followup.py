from app.catalog import load_catalog
from app.followup import Followup
from app.lead import Lead

CLIENT = '<a href="https://t.me/oleg">Олег</a>'


class Notes:
    def __init__(self):
        self.sent: list[str] = []

    async def notify(self, text: str) -> None:
        self.sent.append(text)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make():
    clock, notes = Clock(), Notes()
    return Followup(load_catalog(), notes, idle_minutes=30, clock=clock), clock, notes


async def test_client_who_asked_and_left_is_reported_once():
    f, clock, notes = make()
    f.seen("c1", "Telegram", CLIENT, "Сколько стоит автокран?")
    clock.now = 29 * 60
    assert await f.check() == 0
    clock.now = 31 * 60
    assert await f.check() == 1
    assert await f.check() == 0
    assert notes.sent[0].splitlines() == [
        "💤 Ушёл без заявки (Telegram)",
        f"Клиент: {CLIENT}",
        "Интересовался: Автокран Ивановец 25 т",
        "Последние сообщения: «Сколько стоит автокран?»",
    ]


async def test_unfinished_lead_shows_step_and_data():
    f, clock, notes = make()
    lead = Lead(item=load_catalog().by_id("crane-25"), address="Химки", date="01.12.2026", asked="phone")
    f.seen("c1", "Telegram", CLIENT, "Да", lead=lead)
    clock.now = 3600
    await f.check()
    assert "Заявка: остановился на вопросе «телефон». адрес: Химки, когда: 01.12.2026" in notes.sent[0]


async def test_small_talk_and_known_clients_are_not_reported():
    f, clock, notes = make()
    f.seen("c1", "Telegram", CLIENT, "Привет")  # техникой не интересовался
    f.seen("c2", "Telegram", CLIENT, "Почём кран?", manager_notified=True)  # менеджер уже в курсе
    clock.now = 3600
    assert await f.check() == 0


async def test_returning_client_starts_new_pause():
    f, clock, notes = make()
    f.seen("c1", "Telegram", CLIENT, "Почём камаз?")
    clock.now = 3600
    await f.check()
    f.seen("c1", "Telegram", CLIENT, "А каток есть?")
    clock.now = 3600 + 31 * 60
    await f.check()
    assert len(notes.sent) == 2
    assert "Интересовался: Каток Bomag 7 т" in notes.sent[1]


async def test_client_text_is_escaped():
    f, clock, notes = make()
    f.seen("c1", "Telegram", CLIENT, "кран <b>срочно</b>")
    clock.now = 3600
    await f.check()
    assert "«кран &lt;b&gt;срочно&lt;/b&gt;»" in notes.sent[0]
