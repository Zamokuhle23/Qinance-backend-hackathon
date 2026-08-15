"""Campaign tools for Ask Qinance."""

from decimal import Decimal

from .registry import register_tool


def _campaign_data(campaign):
    return {
        'id': campaign.id,
        'name': campaign.name,
        'discount_percent': float(campaign.discount_percent),
        'latitude': float(campaign.latitude),
        'longitude': float(campaign.longitude),
        'status': campaign.status,
        'merchant_id': campaign.customer_id,
        'merchant_name': campaign.customer.name,
        'created_at': campaign.created_at.isoformat(),
    }


@register_tool(
    'create_discount_campaign',
    roles=['customer', 'merchant', 'agent', 'admin'],
    description='Create and activate a merchant discount campaign after the merchant confirms its name, discount, and location.',
)
def create_discount_campaign(customer_id, name, discount_percent, latitude, longitude):
    from loans.models import Customer, DiscountCampaign

    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        return {'ok': False, 'error': f'Merchant {customer_id} not found'}

    try:
        discount = Decimal(str(discount_percent))
        lat = Decimal(str(latitude))
        lon = Decimal(str(longitude))
    except Exception:
        return {'ok': False, 'error': 'Campaign discount and location must be valid numbers.'}

    if discount <= 0 or discount > 100:
        return {'ok': False, 'error': 'Discount must be greater than 0 and no more than 100 percent.'}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {'ok': False, 'error': 'Campaign location is outside valid latitude/longitude ranges.'}

    campaign = DiscountCampaign.objects.create(
        customer=customer,
        name=str(name).strip()[:150] or f'{discount}% Discount Campaign',
        discount_percent=discount,
        latitude=lat,
        longitude=lon,
        status='active',
    )
    return {'ok': True, 'data': {'campaign': _campaign_data(campaign)}}
