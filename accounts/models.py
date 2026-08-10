# accounts/models.py
from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal

class AgentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    amount_in_hand = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )

    def __str__(self):
        return self.user.username

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import AgentProfile

@receiver(post_save, sender=User)
def create_agent_profile(sender, instance, created, **kwargs):
    if created:
        AgentProfile.objects.create(user=instance)

from django.utils import timezone
from datetime import timedelta
import uuid


class RegistrationToken(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    def is_valid(self):
        """Check if the token is still valid and unused."""
        return not self.used and timezone.now() < self.expires_at

    @classmethod
    def create_token(cls, hours_valid=2):
        """Create a new token valid for a limited time (default: 2 hours)."""
        return cls.objects.create(expires_at=timezone.now() + timedelta(hours=hours_valid))

    def __str__(self):
        return f"{self.token} (expires {self.expires_at})"
    

