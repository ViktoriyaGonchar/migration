"""HTTP-клиент к internal API (бот не подключается к БД сайта)."""

import httpx


class InternalApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Internal-Key": api_key},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def subscription_status(self, subscriber_id: int) -> dict:
        response = await self._client.get(
            "/api/internal/v1/subscriptions/status",
            params={"subscriber_id": subscriber_id},
        )
        response.raise_for_status()
        return response.json()

    async def reissue_link(self, subscriber_id: int) -> str:
        response = await self._client.post(
            "/api/internal/v1/access/reissue",
            json={"subscriber_id": subscriber_id},
        )
        response.raise_for_status()
        return str(response.json()["login_url"])

    async def resolve_subscriber_by_telegram(self, telegram_user_id: int) -> int | None:
        response = await self._client.get(
            "/api/internal/v1/telegram/subscriber",
            params={"telegram_user_id": telegram_user_id},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return int(response.json()["subscriber_id"])

    async def telegram_link_consume(self, token: str, telegram_user_id: int) -> int:
        response = await self._client.post(
            "/api/internal/v1/telegram/link/consume",
            json={"token": token, "telegram_user_id": telegram_user_id},
        )
        response.raise_for_status()
        return int(response.json()["subscriber_id"])

    async def latest_manual_payment_for_telegram(self, telegram_user_id: int) -> dict:
        """Phase 8A: последняя ручная заявка для /pay_status (без review_note)."""
        response = await self._client.get(
            "/api/internal/v1/manual-payment-requests/latest-for-telegram",
            params={"telegram_user_id": telegram_user_id},
        )
        response.raise_for_status()
        return response.json()

    async def create_manual_payment_request(
        self,
        telegram_user_id: int,
        note: str | None = None,
    ) -> dict:
        payload: dict = {"telegram_user_id": telegram_user_id}
        if note is not None:
            payload["note"] = note
        response = await self._client.post(
            "/api/internal/v1/manual-payment-requests",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def create_payment_attempt(
        self,
        telegram_user_id: int,
        provider: str,
        amount_label: str | None = None,
        currency: str | None = None,
    ) -> dict:
        payload: dict = {"telegram_user_id": telegram_user_id, "provider": provider}
        if amount_label is not None:
            payload["amount_label"] = amount_label
        if currency is not None:
            payload["currency"] = currency
        response = await self._client.post("/api/internal/v1/payments", json=payload)
        response.raise_for_status()
        return response.json()

    async def get_payment_attempt(self, attempt_id: int, refresh: bool = False) -> dict:
        params = {"refresh": "true"} if refresh else None
        response = await self._client.get(
            f"/api/internal/v1/payments/{attempt_id}",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def list_payment_attempts(self, telegram_user_id: int, limit: int = 10) -> list:
        response = await self._client.get(
            "/api/internal/v1/payments",
            params={"telegram_user_id": telegram_user_id, "limit": limit},
        )
        response.raise_for_status()
        return response.json()
