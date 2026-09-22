"""Fasada providera OpenAI."""

from __future__ import annotations

from caelo_core.models.openai_models import openai_models

from .client import OpenAIClient
from .chat import OpenAIChatProvider
from .image import OpenAIImageProvider
from .tools import OpenAIAgentTools


class OpenAIProvider:
    id = "openai"
    provider_id = "openai"

    def __init__(self, api_key_provider) -> None:
        self.client = OpenAIClient(api_key_provider)
        # Wspólny callback waliduje brak klucza przed otwarciem strumienia.
        self.chat = OpenAIChatProvider(self.client.api_key)
        self.images = OpenAIImageProvider(self.client)
        self.agent = OpenAIAgentTools(self.client.api_key)

    def validate_connection(self) -> dict:
        known = {model.id for model in openai_models()}
        return self.client.validate_connection(known)

    def available_model_ids(self, *, force: bool = False) -> tuple[str, ...]:
        return self.client.list_models(force=force)

    def stream_chat(self, messages, **options):
        return self.chat.stream_chat(messages, **options)

    def complete_chat(self, messages, *, model=None, **options):
        return self.chat.complete_chat(messages, model=model, **options)

    def generate_image(self, request):
        return self.images.generate_image(request)
