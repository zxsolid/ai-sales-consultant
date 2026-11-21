from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm import LLM, OpenAICompatible, YandexGPT


class Settings(BaseSettings):
    """Настройки из переменных окружения или файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True)

    # Модель: yandex или openai (любой сервис с API как у OpenAI)
    llm_provider: str = "yandex"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = "yandexgpt"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Telegram: демо-бот и чат менеджера, куда падают горячие клиенты
    telegram_bot_token: str = ""
    manager_chat_id: int | None = None

    # Авито: доступ к API мессенджера
    avito_client_id: str = ""
    avito_client_secret: str = ""
    avito_user_id: int | None = None
    avito_webhook_secret: str = ""
    # Через сколько минут тишины сказать менеджеру, что клиент ушёл без заявки
    followup_minutes: float = 30
    # Менеджер сам написал клиенту в Авито: столько часов бот в этом чате молчит
    avito_pause_hours: float = 12
    # Где хранить историю чатов и начатые заявки
    state_path: str = "data/state.sqlite"

    def make_llm(self) -> LLM:
        if self.llm_provider == "yandex":
            if not (self.yandex_api_key and self.yandex_folder_id):
                raise ValueError("Заполните YANDEX_API_KEY и YANDEX_FOLDER_ID в .env")
            return YandexGPT(self.yandex_api_key, self.yandex_folder_id, self.yandex_model)
        if self.llm_provider == "openai":
            if not self.openai_api_key:
                raise ValueError("Заполните OPENAI_API_KEY в .env")
            return OpenAICompatible(self.openai_api_key, self.openai_model, self.openai_base_url)
        raise ValueError(f"Неизвестный LLM_PROVIDER: {self.llm_provider}")
