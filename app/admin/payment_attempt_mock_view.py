"""
Mock confirm/fail для payment_attempts (Phase 7): только sandbox + PAYMENTS_MOCK_UI.
"""

from __future__ import annotations

import logging
from typing import Any

from sqladmin import BaseView, expose
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.config import get_settings
from app.db.session import async_session_maker
from app.services import payment_attempts as payment_attempts_service
from sqlalchemy import select
from app.db.models.payment_attempt import PaymentAttempt

_log = logging.getLogger(__name__)


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


class PaymentAttemptMockView(BaseView):
    """Тестовые переходы статуса; без sandbox/mock_ui — 404."""

    name = "Платежи: mock (тест)"
    name_plural = "Платежи: mock (тест)"
    icon = "fa-solid fa-flask"

    @expose("/payment-attempts-mock", methods=["GET", "POST"], identity="payment_attempts_mock")
    async def mock_page(self, request: Request):
        settings = get_settings()
        if not settings.payments_sandbox_mode or not settings.payments_mock_ui:
            return PlainTextResponse("Not Found", status_code=404)

        title = "Mock: payment attempts"
        error_message: str | None = None
        result_success: str | None = None
        rows: list[PaymentAttempt] = []

        admin_user_id = request.session.get("admin_user_id")
        if admin_user_id is None:
            error_message = "Нет сессии администратора."

        if error_message is None and request.method == "POST":
            form = await request.form()
            action = str(form.get("action") or "").strip()
            aid = _parse_int(form.get("attempt_id"))
            if aid is None:
                error_message = "Некорректный ID."
            elif action not in ("mock_confirm", "mock_fail"):
                error_message = "Неизвестное действие."
            else:
                async with async_session_maker() as session:
                    try:
                        if action == "mock_confirm":
                            await payment_attempts_service.mock_confirm_payment_attempt(
                                session,
                                attempt_id=aid,
                                admin_user_id=int(admin_user_id),
                            )
                        else:
                            await payment_attempts_service.mock_fail_payment_attempt(
                                session,
                                attempt_id=aid,
                                admin_user_id=int(admin_user_id),
                            )
                        await session.commit()
                        result_success = "Статус обновлён (тест)."
                    except ValueError as e:
                        await session.rollback()
                        error_message = str(e)
                    except Exception:
                        await session.rollback()
                        _log.exception("payment_attempt_mock")
                        error_message = "Операция не выполнена."

        if error_message is None or request.method == "GET":
            async with async_session_maker() as session:
                r = await session.execute(
                    select(PaymentAttempt).order_by(PaymentAttempt.id.desc()).limit(40)
                )
                rows = list(r.scalars().all())

        context = {
            "request": request,
            "title": title,
            "error_message": error_message,
            "result_success": result_success,
            "rows": rows,
        }
        return await self.templates.TemplateResponse(
            request,
            "admin/payment_attempts_mock.html",
            context,
        )
