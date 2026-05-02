"""Абстракция платёжных провайдеров (Phase 7: только заглушки)."""

from app.payments.stub_adapters import ADAPTER_BY_PROVIDER, get_adapter, known_providers

__all__ = ["ADAPTER_BY_PROVIDER", "get_adapter", "known_providers"]
