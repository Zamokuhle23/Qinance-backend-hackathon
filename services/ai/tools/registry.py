"""Backend tool registry for Ask Qinance.

Tools are role-aware functions that query the database and return structured JSON.
Gemini never accesses the database directly — it selects a tool, Python executes it.
"""

import inspect
import logging

logger = logging.getLogger(__name__)

# Global tool registry: {tool_name: {'func': ..., 'roles': [...], 'description': ...}}
_TOOL_REGISTRY = {}


def register_tool(name, roles=None, description=''):
    """Decorator to register a backend tool.

    Args:
        name: Unique tool name (e.g. 'search_merchants').
        roles: List of roles allowed to use this tool
               ('customer', 'merchant', 'agent', 'admin').
        description: Short description for Gemini intent detection.

    Usage:
        @register_tool('search_merchants', roles=['customer'], description='...')
        def search_merchants(**params):
            ...
    """

    def decorator(func):
        _roles = roles or ['customer', 'merchant', 'agent', 'admin']
        _TOOL_REGISTRY[name] = {
            'func': func,
            'roles': _roles,
            'description': description,
            'signature': str(inspect.signature(func)),
        }
        logger.info('Registered AI tool: %s (roles=%s)', name, roles)
        return func
    return decorator


class ToolRegistry:
    """Queryable registry of backend AI tools."""

    @staticmethod
    def get(name):
        """Get tool metadata by name or raise KeyError."""
        return _TOOL_REGISTRY.get(name)

    @staticmethod
    def get_func(name):
        """Get the callable for a tool."""
        entry = _TOOL_REGISTRY.get(name)
        return entry['func'] if entry else None

    @staticmethod
    def list(role=None):
        """List all tools, optionally filtered by role."""
        tools = []
        for name, entry in _TOOL_REGISTRY.items():
            if role and role not in entry['roles']:
                continue
            tools.append({
                'name': name,
                'roles': entry['roles'],
                'description': entry['description'],
                'signature': entry['signature'],
            })
        return tools

    @staticmethod
    def call(name, **params):
        """Execute a tool safely. Returns structured JSON or error dict."""
        func = ToolRegistry.get_func(name)
        if not func:
            return {'ok': False, 'error': f'Unknown tool: {name}'}
        try:
            result = func(**params)
            if not isinstance(result, dict):
                return {'ok': True, 'data': result}
            result.setdefault('ok', True)
            return result
        except TypeError as e:
            logger.error('Tool %s called with invalid params: %s', name, e)
            return {'ok': False, 'error': f'Invalid parameters for {name}: {e}'}
        except Exception as e:
            logger.error('Tool %s failed: %s', name, e)
            return {'ok': False, 'error': f'{name} failed: {e}'}


# Re-export helpers
get_tool = ToolRegistry.get
list_tools = ToolRegistry.list