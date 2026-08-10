import json
import time
import logging
import random
import google.genai as genai

from .config import AIConfig

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Gemini API provider implementation."""

    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 2  # seconds

    def __init__(self, model=None):
        self.client = genai.Client(
            enterprise=True,
            project="project-dc3f5fcd-73e6-4b41-989",
            location="us-central1"
        )
        # Force gemini-2.5-flash as it is the ONLY model registered and enabled in their Vertex AI us-central1 project
        self.model = "gemini-2.5-flash"

    def generate(self, prompt, system_prompt=None, temperature=None, max_tokens=None):
        """
        Send a prompt to Gemini and return the text response.

        Returns:
            dict: {
                'text': str,
                'tokens': int,
                'latency_ms': int,
                'success': bool,
                'error': str | None,
            }
        """
        start = time.time()
        try:
            contents = []
            if system_prompt:
                contents.append({'role': 'user', 'parts': [{'text': system_prompt}]})
            contents.append({'role': 'user', 'parts': [{'text': prompt}]})

            # Retry with exponential backoff on rate limits (429) and transient errors
            last_error = None
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                    )
                    text = response.text
                    tokens = 0  # Not easily available with the new client
                    latency_ms = int((time.time() - start) * 1000)
                    return {
                        'text': text.strip(),
                        'tokens': tokens,
                        'latency_ms': latency_ms,
                        'success': True,
                        'error': None,
                    }
                except Exception as e:
                    error_str = str(e)
                    last_error = e
                    # Retry on rate limit (429 / RESOURCE_EXHAUSTED) and 5xx server errors
                    is_retryable = '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or error_str.strip().startswith('5')
                    if is_retryable and attempt < self.MAX_RETRIES - 1:
                        delay = self.BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            'Gemini API transient error (attempt %d/%d): %s. Retrying in %.1fs...',
                            attempt + 1, self.MAX_RETRIES, error_str, delay
                        )
                        time.sleep(delay)
                        continue
                    break

            # All retries exhausted
            latency_ms = int((time.time() - start) * 1000)
            logger.error('Gemini API error after %d attempts: %s', self.MAX_RETRIES, last_error)
            return {
                'text': '',
                'tokens': 0,
                'latency_ms': latency_ms,
                'success': False,
                'error': str(last_error),
            }

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.error('Gemini API error: %s', e)
            return {
                'text': '',
                'tokens': 0,
                'latency_ms': latency_ms,
                'success': False,
                'error': str(e),
            }

    def generate_json(self, prompt, system_prompt=None, temperature=None, max_tokens=None):
        """
        Send a prompt to Gemini and parse the JSON response.

        Returns:
            dict: {
                'data': dict | None,
                'tokens': int,
                'latency_ms': int,
                'success': bool,
                'error': str | None,
            }
        """
        result = self.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not result['success']:
            return {
                'data': None,
                'tokens': result['tokens'],
                'latency_ms': result['latency_ms'],
                'success': False,
                'error': result['error'],
            }

        try:
            text = result['text']
            if '```' in text:
                import re
                match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if match:
                    text = match.group(1)
            data = json.loads(text)
            return {
                'data': data,
                'tokens': result['tokens'],
                'latency_ms': result['latency_ms'],
                'success': True,
                'error': None,
            }
        except json.JSONDecodeError as e:
            logger.error('Failed to parse Gemini JSON response: %s', e)
            return {
                'data': None,
                'tokens': result['tokens'],
                'latency_ms': result['latency_ms'],
                'success': False,
                'error': f'Failed to parse AI response as JSON: {e}',
            }