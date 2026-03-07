"""AI task router — selects provider per task type with lazy init and caching."""
import logging
from typing import Dict, Optional

from scatter.ai.base import AIProvider, AITaskType
from scatter.config import ScatterConfig


class AIRouter:
    """Select the best AI provider for a given task type.

    Resolution order for provider selection:
    1. task_overrides[task_type] if specified in config
    2. default_provider from config

    Providers are lazily created on first use and cached for reuse.
    Returns None if the provider cannot be created (e.g. missing credentials).
    """

    def __init__(self, config: ScatterConfig):
        self._config = config
        self._providers: Dict[str, AIProvider] = {}

    def get_provider(self, task_type: Optional[AITaskType] = None) -> Optional[AIProvider]:
        """Get the best provider for a task type.

        Returns None if provider can't be created or doesn't support the task.
        """
        provider_name = self._config.ai.default_provider

        if task_type is not None:
            override = self._config.ai.task_overrides.get(task_type.value)
            if override:
                provider_name = override

        provider = self._get_or_create(provider_name)
        if provider is None:
            return None

        if task_type is not None and not provider.supports(task_type):
            logging.warning(
                f"Provider '{provider_name}' does not support task type "
                f"'{task_type.value}'. Returning None."
            )
            return None

        return provider

    def _get_or_create(self, provider_name: str) -> Optional[AIProvider]:
        """Get a cached provider or create one."""
        if provider_name in self._providers:
            return self._providers[provider_name]

        provider = self._create_provider(provider_name)
        if provider is not None:
            self._providers[provider_name] = provider
        return provider

    def _create_provider(self, provider_name: str) -> Optional[AIProvider]:
        """Create a provider by name. Returns None on failure."""
        if provider_name == "gemini":
            return self._create_gemini()

        logging.warning(f"Unknown AI provider: '{provider_name}'")
        return None

    def _create_gemini(self) -> Optional[AIProvider]:
        """Create a GeminiProvider from config credentials.

        Note: GeminiProvider.__init__ has its own GOOGLE_API_KEY env-var
        fallback when api_key is None.  This means the env var can bypass
        the config precedence chain if no layer provides a key.  This is
        intentional for backward compatibility — standalone
        ``GeminiProvider()`` callers expect the env-var fallback.  When
        the config system *does* resolve a key, it is passed here and
        takes priority.
        """
        from scatter.ai.providers.gemini_provider import GeminiProvider

        api_key = self._config.ai.credentials.get("gemini", {}).get("api_key")
        model_name = self._config.ai.gemini_model

        try:
            return GeminiProvider(api_key=api_key, model_name=model_name)
        except Exception as e:
            logging.warning(f"Could not create Gemini provider: {e}")
            return None
