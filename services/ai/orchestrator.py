"""AIOrchestrator — the central brain for Ask Qinance.

Flow:
    User message
        ↓
    AIOrchestrator.handle(user, role, context)
        ↓
    Gemini intent detection (which tool(s) to call)
        ↓
    Backend tool execution (Python queries the database)
        ↓
    Structured JSON results
        ↓
    Gemini formats the final response (explains results)
        ↓
    Reply to user

Gemini never accesses the database directly.
Python always performs calculations.
"""

import json
import logging
import time

from .ai_service import AIService
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# System prompt instructs Gemini to only choose a tool; it never executes it.
ORCHESTRATOR_SYSTEM = (
    "You are Ask Qinance, the Qinance AI assistant. "
    "About Qinance: Qinance is a fintech platform in Eswatini that integrates digital payments and business financing. "
    "Customers use it to pay merchants (via QR/NFC/Sound), track wallets, and discover deals. "
    "Merchants use it to accept payments, run discount/cashback campaigns, and apply for business loans (working capital). "
    "Agents are authorized field workers who collect repayments from merchants. "
    "To become a merchant, users create an account on the Merchant Portal and upload KYC docs. "
    "You do NOT access databases directly. "
    "You ONLY select which backend tool to use by returning JSON with a 'tool' field. "
    "After a tool returns structured JSON, you explain the results in plain language. "
    "You never invent numbers — only report what the tool returned. "
    "If no tool fits, return tool 'none' and answer from general knowledge."
)

INTENT_PROMPT = """
User role: {role}
User message: {message}

Available tools:
{tools}

Return JSON with exactly these fields:
{{
  "tool": "tool_name or 'none'",
  "params": {{ ...tool parameters... }},
  "reasoning": "Why this tool was chosen"
}}
"""

EXPLAIN_PROMPT = """
User role: {role}
User message: {message}
Tool executed: {tool}
Tool result: {result}

Explain the result to the user in clear, friendly language.
Use bullet points where helpful. Do not include raw JSON unless asked.
Never invent data. Only report what the tool returned.
"""


class AIOrchestrator:
    """Central orchestration for Ask Qinance."""

    def __init__(self):
        self.ai_service = AIService()

    def handle(self, message, role='customer', context=None):
        """
        Handle a user message end-to-end.

        Args:
            message: The user's natural-language question.
            role: 'customer', 'merchant', 'agent', or 'admin'.
            context: Optional dict with user identifiers (customer_id,
                     merchant_id, agent_id) used to populate tool params.

        Returns:
            dict with reply, tool, tool_result, intent_latency_ms,
            response_latency_ms, tokens.
        """
        context = context or {}
        start = time.time()

        # 1. Intent detection: Gemini picks a tool (never executes it).
        intent = self._detect_intent(message, role)
        tool_name = intent.get('tool', 'none')
        params = intent.get('params', {}) or {}

        # Merge context identifiers into params when missing.
        for key, value in context.items():
            params.setdefault(key, value)

        # 2. Execute the backend tool (Python queries the database).
        tool_result = None
        if tool_name != 'none':
            allowed = ToolRegistry.get(tool_name)
            if not allowed:
                tool_result = {'ok': False, 'error': f'Unknown tool: {tool_name}'}
                tool_name = 'none'
            elif role not in allowed['roles']:
                tool_result = {'ok': False, 'error': f'Tool {tool_name} is not allowed for role {role}'}
                tool_name = 'none'
            else:
                tool_result = ToolRegistry.call(tool_name, **params)

        intent_latency_ms = int((time.time() - start) * 1000)

        # 3. If no tool was selected, fall back to a plain response.
        if tool_name == 'none':
            reply = self._fallback_reply(message, role)
            return {
                'reply': reply,
                'tool': None,
                'tool_result': None,
                'intent_latency_ms': intent_latency_ms,
                'response_latency_ms': int((time.time() - start) * 1000),
            }

        # 4. Gemini formats the final response from the tool's JSON.
        explain_prompt = EXPLAIN_PROMPT.format(
            role=role,
            message=message,
            tool=tool_name,
            result=json.dumps(tool_result, default=str),
        )
        response = self.ai_service.generate(
            explain_prompt,
            system_prompt=ORCHESTRATOR_SYSTEM,
            feature='ask_qinance',
            user_role=role,
        )

        reply = response.get('text', '')
        if not reply and response.get('success'):
            reply = 'I could not interpret that result. Please try again.'
        if not response.get('success'):
            reply = f'I encountered an error: {response.get("error", "unknown")}'

        return {
            'reply': reply,
            'tool': tool_name,
            'tool_result': tool_result,
            'intent_latency_ms': intent_latency_ms,
            'response_latency_ms': int((time.time() - start) * 1000),
            'tokens': response.get('tokens', 0),
        }

    def _detect_intent(self, message, role):
        """Ask Gemini to select a tool — Gemini never executes anything."""
        tools = ToolRegistry.list(role=role)
        if not tools:
            return {'tool': 'none', 'params': {}, 'reasoning': 'No tools available for this role.'}

        prompt = INTENT_PROMPT.format(
            role=role,
            message=message,
            tools=json.dumps(tools),
        )
        result = self.ai_service.generate_json(
            prompt,
            system_prompt=ORCHESTRATOR_SYSTEM,
            feature=f'ask_qinance_intent_{role}',
            user_role=role,
        )
        if not result['success']:
            logger.warning('Intent detection failed: %s', result.get('error'))
            return {'tool': 'none', 'params': {}, 'reasoning': result.get('error', '')}
        return result['data'] or {'tool': 'none', 'params': {}}

    def _fallback_reply(self, message, role):
        """Plain explanation without tools (used when no tool matches)."""
        prompt = (
            f"The user ({role}) asked: {message}\n\n"
            "You are Ask Qinance. Respond helpfully from general knowledge. "
            "Do not invent platform data. If the question needs platform data "
            "that no tool can provide, say that this is not available yet."
        )
        result = self.ai_service.generate(
            prompt,
            system_prompt=ORCHESTRATOR_SYSTEM,
            feature='ask_qinance_fallback',
            user_role=role,
        )
        return result.get('text', 'I am sorry, I could not answer that.')