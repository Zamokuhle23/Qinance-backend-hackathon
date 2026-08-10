"""Admin tools for Ask Qinance — merchant-backend.

Admin tools aggregate AI usage statistics and platform health metrics.
"""

from .registry import register_tool


@register_tool(
    'platform_ai_stats',
    roles=['admin'],
    description='Returns AI usage statistics: total requests, success rate, average latency, token usage.',
)
def platform_ai_stats():
    from loans.models import AILog
    from django.db.models import Count, Avg, Sum

    logs = AILog.objects.all()
    total = logs.count()
    success = logs.filter(success=True).count()
    return {
        'ok': True,
        'data': {
            'total_requests': total,
            'success_count': success,
            'failure_count': total - success,
            'success_rate': round((success / total) * 100, 1) if total else 0,
            'avg_latency_ms': logs.aggregate(avg=Avg('latency_ms'))['avg'] or 0,
            'total_tokens': logs.aggregate(total=Sum('tokens'))['total'] or 0,
            'feature_usage': list(
                logs.values('feature').annotate(count=Count('id')).order_by('-count')
            ),
        }
    }


@register_tool(
    'merchant_statistics',
    roles=['admin'],
    description='Returns merchant statistics: total merchants, active, loans outstanding.',
)
def merchant_statistics():
    from loans.models import Customer, Loan
    from django.db.models import Sum

    total_customers = Customer.objects.count()
    blacklisted = Customer.objects.filter(blacklisted=True).count()
    active_loans = Loan.objects.filter(status='active')
    return {
        'ok': True,
        'data': {
            'total_merchants': total_customers,
            'blacklisted_merchants': blacklisted,
            'active_loans': active_loans.count(),
            'outstanding_principal': float(
                active_loans.aggregate(total=Sum('principal_amount'))['total'] or 0
            ),
        }
    }


@register_tool(
    'feature_usage',
    roles=['admin'],
    description='Returns AI feature usage breakdown.',
)
def feature_usage():
    from loans.models import AILog
    from django.db.models import Count

    return {
        'ok': True,
        'data': {
            'features': list(
                AILog.objects.values('feature')
                .annotate(count=Count('id'))
                .order_by('-count')
            )
        }
    }