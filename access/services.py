import secrets
from typing import Optional

from django.utils import timezone

from .models import AccessToken


def generate_token_value(length: int = 32) -> str:
    return secrets.token_urlsafe(length)[:64]


def generate_unique_token_value(length: int = 32) -> str:
    while True:
        token_value = generate_token_value(length=length)
        if not AccessToken.objects.filter(token=token_value).exists():
            return token_value


def create_access_token(
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    notes: str = "",
) -> AccessToken:
    return AccessToken.objects.create(
        token=generate_unique_token_value(),
        email=email or None,
        full_name=full_name or None,
        notes=notes,
    )


def is_token_usable(token_obj: AccessToken) -> bool:
    if not token_obj.is_active:
        return False
    if token_obj.expires_at and token_obj.expires_at <= timezone.now():
        return False
    return True


def get_valid_token(token_value: str) -> Optional[AccessToken]:
    token_obj = AccessToken.objects.filter(token=token_value).first()
    if not token_obj:
        return None
    if not is_token_usable(token_obj):
        return None
    return token_obj


def mark_token_used(token_obj: AccessToken) -> None:
    token_obj.last_used_at = timezone.now()
    token_obj.save(update_fields=["last_used_at"])
