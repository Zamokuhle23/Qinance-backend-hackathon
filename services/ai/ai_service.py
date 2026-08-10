import logging
import time
from django.core.cache import cache

from .config import AIConfig
from .gemini_provider import GeminiProvider

logger = logging.getLogger(__name__)


class AIService:
    """
    Reusable AI service that internally calls the configured provider.
    Future providers (Claude, OpenAI, DeepSeek) can be added without
    changing business logic.
    """

    _provider = None

    def __init__(self):
        self.provider = self._get_provider()

    @classmethod
    def _get_provider(cls):
        """Return the provider instance based on AI_PROVIDER config."""
        if cls._provider is None:
            provider_config = AIConfig.get_provider_config()
            provider_name = provider_config['provider']
            if provider_name == 'gemini':
                cls._provider = GeminiProvider(
                    model=provider_config['model'],
                )
            # Future providers can be added here:
            # elif provider_name == 'claude':
            #     cls._provider = ClaudeProvider(...)
            # elif provider_name == 'openai':
            #     cls._provider = OpenAIProvider(...)
            # elif provider_name == 'deepseek':
            #     cls._provider = DeepSeekProvider(...)
            else:
                cls._provider = GeminiProvider(
                    model=provider_config['model'],
                )
        return cls._provider

    def generate(self, prompt, system_prompt=None, feature='general', user_role=None, temperature=None, max_tokens=None, tool_used=None, intent=None):
        """
        Generate a text response from the AI provider.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.
            feature: Feature name for logging (e.g. 'loan_advisor').
            user_role: Role of the requesting user (customer, merchant, agent, admin).
            temperature: Optional override.
            max_tokens: Optional override.
            tool_used: Optional backend tool name used by the orchestrator.
            intent: Optional detected intent.

        Returns:
            dict with text, tokens, latency_ms, success, error.
        """
        start = time.time()
        result = self.provider.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.time() - start) * 1000)

        # Log the AI request (cache_hit=False — this is a real provider call)
        self._log_request(
            feature=feature,
            user_role=user_role,
            tokens=result.get('tokens', 0),
            latency_ms=result.get('latency_ms', latency_ms),
            success=result.get('success', False),
            error=result.get('error'),
            cache_hit=False,
            tool_used=tool_used,
            intent=intent,
            response_time=latency_ms,
        )

        return result

    def generate_json(self, prompt, system_prompt=None, feature='general', user_role=None, temperature=None, max_tokens=None, tool_used=None, intent=None):
        """
        Generate a JSON response from the AI provider.

        Returns:
            dict with data, tokens, latency_ms, success, error.
        """
        start = time.time()
        result = self.provider.generate_json(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.time() - start) * 1000)

        # Log the AI request (cache_hit=False — this is a real provider call)
        self._log_request(
            feature=feature,
            user_role=user_role,
            tokens=result.get('tokens', 0),
            latency_ms=result.get('latency_ms', latency_ms),
            success=result.get('success', False),
            error=result.get('error'),
            cache_hit=False,
            tool_used=tool_used,
            intent=intent,
            response_time=latency_ms,
        )

        return result

    def _log_request(self, feature, user_role, tokens, latency_ms, success, error=None, cache_hit=False, tool_used='', intent='', response_time=0):
        """Log AI request metadata. Never log prompts or sensitive data."""
        if not AIConfig.AI_LOGGING_ENABLED:
            return
        try:
            from loans.models import AILog
            AILog.objects.create(
                feature=feature,
                user_role=user_role or '',
                model=AIConfig.GEMINI_MODEL,
                provider=AIConfig.AI_PROVIDER,
                tokens=tokens,
                latency_ms=latency_ms,
                success=success,
                error=error or '',
                cache_hit=cache_hit,
                tool_used=tool_used or '',
                intent=intent or '',
                response_time=response_time,
            )
        except Exception as e:
            logger.warning('Failed to log AI request: %s', e)

    def get_cached_or_generate(self, cache_key, prompt, system_prompt=None, feature='general', user_role=None, ttl=None, tool_used=None, intent=None):
        """
        Get a cached AI response or generate a new one.

        Args:
            cache_key: Unique cache key for this response.
            prompt: The prompt to send.
            system_prompt: Optional system instructions.
            feature: Feature name for logging.
            user_role: Role of the requesting user.
            ttl: Cache TTL in seconds. Defaults to AIConfig.AI_CACHE_TTL.
            tool_used: Optional backend tool name.
            intent: Optional detected intent.

        Returns:
            dict with text, tokens, latency_ms, success, error, cached.
        """
        ttl = ttl or AIConfig.AI_CACHE_TTL
        cached = cache.get(cache_key)
        if cached is not None:
            # Log a cache hit (no provider call)
            if AIConfig.AI_LOGGING_ENABLED:
                try:
                    from loans.models import AILog
                    AILog.objects.create(
                        feature=feature,
                        user_role=user_role or '',
                        model=AIConfig.GEMINI_MODEL,
                        provider=AIConfig.AI_PROVIDER,
                        tokens=0,
                        latency_ms=0,
                        success=True,
                        cache_hit=True,
                        tool_used=tool_used or '',
                        intent=intent or '',
                        response_time=0,
                    )
                except Exception as e:
                    logger.warning('Failed to log AI cache hit: %s', e)
            return {**cached, 'cached': True}

        result = self.generate(
            prompt,
            system_prompt=system_prompt,
            feature=feature,
            user_role=user_role,
            tool_used=tool_used,
            intent=intent,
        )
        result['cached'] = False
        if result['success']:
            cache.set(cache_key, result, timeout=ttl)
        return result

    def get_cached_or_generate_json(self, cache_key, prompt, system_prompt=None, feature='general', user_role=None, ttl=None, tool_used=None, intent=None):
        """
        Get a cached AI JSON response or generate a new one.

        Returns:
            dict with data, tokens, latency_ms, success, error, cached.
        """
        ttl = ttl or AIConfig.AI_CACHE_TTL
        cached = cache.get(cache_key)
        if cached is not None:
            # Log a cache hit (no provider call)
            if AIConfig.AI_LOGGING_ENABLED:
                try:
                    from loans.models import AILog
                    AILog.objects.create(
                        feature=feature,
                        user_role=user_role or '',
                        model=AIConfig.GEMINI_MODEL,
                        provider=AIConfig.AI_PROVIDER,
                        tokens=0,
                        latency_ms=0,
                        success=True,
                        cache_hit=True,
                        tool_used=tool_used or '',
                        intent=intent or '',
                        response_time=0,
                    )
                except Exception as e:
                    logger.warning('Failed to log AI cache hit: %s', e)
            return {**cached, 'cached': True}

        result = self.generate_json(
            prompt,
            system_prompt=system_prompt,
            feature=feature,
            user_role=user_role,
            tool_used=tool_used,
            intent=intent,
        )
        result['cached'] = False
        if result['success']:
            cache.set(cache_key, result, timeout=ttl)
        return result
