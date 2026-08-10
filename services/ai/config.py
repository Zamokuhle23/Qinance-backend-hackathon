import os
from decouple import config


class AIConfig:
    """Central AI configuration loaded from environment variables."""

    # Provider selection: gemini (default), claude, openai, deepseek
    AI_PROVIDER = config('AI_PROVIDER', default='gemini')

    # Gemini settings
    GEMINI_API_KEY = config('GEMINI_API_KEY', default='')
    GEMINI_MODEL = config('GEMINI_MODEL', default='gemini-1.5-pro')

    # Generic provider settings (future providers)
    CLAUDE_API_KEY = config('CLAUDE_API_KEY', default='')
    CLAUDE_MODEL = config('CLAUDE_MODEL', default='claude-3-5-sonnet-latest')

    OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
    OPENAI_MODEL = config('OPENAI_MODEL', default='gpt-4o-mini')

    DEEPSEEK_API_KEY = config('DEEPSEEK_API_KEY', default='')
    DEEPSEEK_MODEL = config('DEEPSEEK_MODEL', default='deepseek-chat')

    # Generation settings
    TEMPERATURE = config('AI_TEMPERATURE', default=0.3, cast=float)
    MAX_TOKENS = config('AI_MAX_TOKENS', default=1024, cast=int)

    # Cache TTL for AI summaries (seconds) — default 24 hours
    AI_CACHE_TTL = config('AI_CACHE_TTL', default=86400, cast=int)

    # Logging
    AI_LOGGING_ENABLED = config('AI_LOGGING_ENABLED', default=True, cast=bool)

    @classmethod
    def get_provider_config(cls):
        """Return the config dict for the active provider."""
        provider = cls.AI_PROVIDER.lower()
        if provider == 'gemini':
            return {
                'provider': 'gemini',
                'api_key': cls.GEMINI_API_KEY,
                'model': cls.GEMINI_MODEL,
            }
        elif provider == 'claude':
            return {
                'provider': 'claude',
                'api_key': cls.CLAUDE_API_KEY,
                'model': cls.CLAUDE_MODEL,
            }
        elif provider == 'openai':
            return {
                'provider': 'openai',
                'api_key': cls.OPENAI_API_KEY,
                'model': cls.OPENAI_MODEL,
            }
        elif provider == 'deepseek':
            return {
                'provider': 'deepseek',
                'api_key': cls.DEEPSEEK_API_KEY,
                'model': cls.DEEPSEEK_MODEL,
            }
        return {
            'provider': 'gemini',
            'api_key': cls.GEMINI_API_KEY,
            'model': cls.GEMINI_MODEL,
        }