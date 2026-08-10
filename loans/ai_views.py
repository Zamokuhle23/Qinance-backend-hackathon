from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from .models import Customer, AILog
from services.ai.loan_advisor import LoanAdvisor
from services.ai.business_advisor import BusinessAdvisor
from services.ai.orchestrator import AIOrchestrator


class LoanAdviceAPIView(APIView):
    """Get AI loan advice for a customer. Advisory only — never approves loans."""

    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        advisor = LoanAdvisor()
        result = advisor.get_loan_advice(customer)
        if not result['success']:
            return Response({'error': result['error']}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({
            'customer_id': customer.id,
            'customer_name': customer.name,
            'advice': result['advice'],
            'tokens': result.get('tokens', 0),
            'latency_ms': result.get('latency_ms', 0),
        })


class BusinessHealthAPIView(APIView):
    """Get AI business health score for a customer. Advisory only."""

    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        advisor = BusinessAdvisor()
        result = advisor.get_business_health(customer)
        if not result['success']:
            return Response({'error': result['error']}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({
            'customer_id': customer.id,
            'customer_name': customer.name,
            'health': result['health'],
            'tokens': result.get('tokens', 0),
            'latency_ms': result.get('latency_ms', 0),
        })


class AskQinanceAPIView(APIView):
    """Universal Ask Qinance endpoint.

    Accepts a role-aware natural-language message, runs it through the
    AIOrchestrator (intent detection → backend tool → Gemini explanation),
    and returns the reply. Gemini never accesses the database directly.
    """

    def post(self, request):
        message = request.data.get('message', '').strip()
        role = request.data.get('role', 'customer')
        if not message:
            return Response({'error': 'message is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Role guard — only allow known roles.
        if role not in ('customer', 'merchant', 'agent', 'admin'):
            return Response({'error': 'Invalid role.'}, status=status.HTTP_400_BAD_REQUEST)

        # Context identifiers used to populate tool params.
        context = {}
        for key in ('customer_id', 'agent_id', 'merchant_id'):
            value = request.data.get(key)
            if value is not None:
                context[key] = value

        orchestrator = AIOrchestrator()
        result = orchestrator.handle(message, role=role, context=context)

        return Response({
            'reply': result['reply'],
            'tool': result.get('tool'),
            'tool_result': result.get('tool_result'),
            'intent_latency_ms': result.get('intent_latency_ms', 0),
            'response_latency_ms': result.get('response_latency_ms', 0),
            'tokens': result.get('tokens', 0),
        })


class AILogListAPIView(APIView):
    """Admin: list AI request logs."""

    def get(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': 'Unauthorized.'}, status=status.HTTP_403_FORBIDDEN)
        logs = AILog.objects.all()[:100]
        return Response([{
            'id': log.id,
            'feature': log.feature,
            'user_role': log.user_role,
            'model': log.model,
            'provider': log.provider,
            'tokens': log.tokens,
            'latency_ms': log.latency_ms,
            'success': log.success,
            'error': log.error,
            'cache_hit': log.cache_hit,
            'tool_used': log.tool_used,
            'intent': log.intent,
            'response_time': log.response_time,
            'created_at': log.created_at,
        } for log in logs])


class AILogStatsAPIView(APIView):
    """Admin: AI usage statistics for the Google Competition Dashboard."""

    def get(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': 'Unauthorized.'}, status=status.HTTP_403_FORBIDDEN)
        from django.db.models import Count, Avg, Sum
        logs = AILog.objects.all()
        total = logs.count()
        success = logs.filter(success=True).count()
        cache_hits = logs.filter(cache_hit=True).count()
        return Response({
            'total_requests': total,
            'success_count': success,
            'failure_count': total - success,
            'success_rate': round((success / total) * 100, 1) if total else 0,
            'avg_latency_ms': logs.aggregate(avg=Avg('latency_ms'))['avg'] or 0,
            'total_tokens': logs.aggregate(total=Sum('tokens'))['total'] or 0,
            'cache_hits': cache_hits,
            'cache_hit_rate': round((cache_hits / total) * 100, 1) if total else 0,
            'feature_usage': list(
                logs.values('feature').annotate(count=Count('id')).order_by('-count')
            ),
            'tool_usage': list(
                logs.exclude(tool_used='').values('tool_used').annotate(count=Count('id')).order_by('-count')
            ),
            'recent': list(
                logs.values('feature', 'user_role', 'model', 'provider', 'tokens', 'latency_ms', 'success', 'cache_hit', 'tool_used', 'created_at')[:20]
            ),
        })