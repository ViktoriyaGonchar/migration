"""
SQLAdmin skeleton: только просмотр сущностей, без выдачи plaintext login token.
Cookie админки — отдельное имя (см. config.admin_session_cookie_name), middleware только на подприложении /admin.
"""

from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy import select
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.admin.operator_view import OperatorView
from app.admin.payment_attempt_mock_view import PaymentAttemptMockView
from app.admin.payment_review_view import PaymentReviewView
from app.config import Settings
from app.db.models.admin_user import AdminUser
from app.db.models.audit_log import AuditLog
from app.db.models.login_token import LoginToken
from app.db.models.manual_payment_request import ManualPaymentRequest
from app.db.models.payment_attempt import PaymentAttempt
from app.db.models.subscriber import Subscriber
from app.db.models.subscription import Subscription
from app.db.models.web_session import WebSession
from app.db.session import async_session_maker, engine
from fastapi import FastAPI

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class MigrationAdminAuth(AuthenticationBackend):
    """
    Кастомный backend: отдельное имя cookie сессии админки (не смешивать с mc_user_session).
    Не вызываем super().__init__, чтобы задать свой SessionMiddleware с session_cookie.
    """

    def __init__(
        self,
        secret_key: str,
        session_cookie: str,
        https_only: bool,
        session_maker,
    ) -> None:
        self.session_maker = session_maker
        self.middlewares = [
            Middleware(
                SessionMiddleware,
                secret_key=secret_key,
                session_cookie=session_cookie,
                same_site="lax",
                https_only=https_only,
            ),
        ]

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        async with self.session_maker() as session:
            r = await session.execute(select(AdminUser).where(AdminUser.email == username))
            admin = r.scalar_one_or_none()
            if admin is None or not admin.is_active:
                return False
            if not _pwd.verify(password, admin.password_hash):
                return False
            # Сброс сессии до выдачи новой — снижает риск session fixation для админки.
            request.session.clear()
            request.session["admin_user_id"] = admin.id
            return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_id = request.session.get("admin_user_id")
        if admin_id is None:
            return False
        async with self.session_maker() as session:
            admin = await session.get(AdminUser, admin_id)
            return admin is not None and bool(admin.is_active)


class SubscriberAdmin(ModelView, model=Subscriber):
    name = "Подписчик"
    name_plural = "Подписчики"
    can_create = can_edit = can_delete = False


class SubscriptionAdmin(ModelView, model=Subscription):
    name = "Подписка"
    name_plural = "Подписки"
    can_create = can_edit = can_delete = False


class LoginTokenAdmin(ModelView, model=LoginToken):
    name = "Login token"
    name_plural = "Login tokens"
    can_create = can_edit = can_delete = False


class WebSessionAdmin(ModelView, model=WebSession):
    name = "Web session"
    name_plural = "Web sessions"
    can_create = can_edit = can_delete = False


class AuditLogAdmin(ModelView, model=AuditLog):
    name = "Audit"
    name_plural = "Audit logs"
    can_create = can_edit = can_delete = False


class AdminUserAdmin(ModelView, model=AdminUser):
    name = "Админ"
    name_plural = "Админы"
    can_create = can_edit = can_delete = False


class PaymentAttemptAdmin(ModelView, model=PaymentAttempt):
    name = "Попытка оплаты (stub)"
    name_plural = "Попытки оплаты (Phase 7)"
    can_create = can_edit = can_delete = False
    column_default_sort = [(PaymentAttempt.id, True)]
    column_list = [
        PaymentAttempt.id,
        PaymentAttempt.created_at,
        PaymentAttempt.provider,
        PaymentAttempt.provider_payment_id,
        PaymentAttempt.status,
        PaymentAttempt.telegram_user_id,
        PaymentAttempt.subscriber_id,
        PaymentAttempt.amount_label,
        PaymentAttempt.currency,
    ]
    column_details_list = [
        PaymentAttempt.id,
        PaymentAttempt.created_at,
        PaymentAttempt.updated_at,
        PaymentAttempt.provider,
        PaymentAttempt.provider_payment_id,
        PaymentAttempt.telegram_user_id,
        PaymentAttempt.subscriber_id,
        PaymentAttempt.amount_label,
        PaymentAttempt.currency,
        PaymentAttempt.status,
        PaymentAttempt.metadata_json,
        PaymentAttempt.manual_payment_request_id,
    ]


class ManualPaymentRequestAdmin(ModelView, model=ManualPaymentRequest):
    name = "Заявка на оплату"
    name_plural = "Заявки на оплату (ручная проверка)"
    can_create = can_edit = can_delete = False
    # Сначала свежие заявки; сортировка по колонкам в списке.
    column_default_sort = [(ManualPaymentRequest.created_at, True)]
    column_sortable_list = [
        ManualPaymentRequest.id,
        ManualPaymentRequest.created_at,
        ManualPaymentRequest.status,
        ManualPaymentRequest.telegram_user_id,
        ManualPaymentRequest.subscriber_id,
    ]
    column_list = [
        ManualPaymentRequest.id,
        ManualPaymentRequest.created_at,
        ManualPaymentRequest.telegram_user_id,
        ManualPaymentRequest.subscriber_id,
        ManualPaymentRequest.status,
        ManualPaymentRequest.reviewed_at,
        ManualPaymentRequest.reviewed_by_admin_id,
        ManualPaymentRequest.review_note,
        ManualPaymentRequest.amount_label_snapshot,
    ]
    column_details_list = [
        ManualPaymentRequest.id,
        ManualPaymentRequest.created_at,
        ManualPaymentRequest.telegram_user_id,
        ManualPaymentRequest.subscriber_id,
        ManualPaymentRequest.status,
        ManualPaymentRequest.reviewed_at,
        ManualPaymentRequest.reviewed_by_admin_id,
        ManualPaymentRequest.review_note,
        ManualPaymentRequest.operator_note,
        ManualPaymentRequest.amount_label_snapshot,
    ]


def init_sqladmin(app: FastAPI, settings: Settings) -> Admin:
    auth = MigrationAdminAuth(
        secret_key=settings.admin_session_secret,
        session_cookie=settings.admin_session_cookie_name,
        https_only=settings.cookie_secure,
        session_maker=async_session_maker,
    )
    admin = Admin(
        app,
        engine,
        authentication_backend=auth,
        base_url="/admin",
        title="Migration Compass Admin",
    )
    admin.add_view(SubscriberAdmin)
    admin.add_view(SubscriptionAdmin)
    admin.add_view(LoginTokenAdmin)
    admin.add_view(WebSessionAdmin)
    admin.add_view(AuditLogAdmin)
    admin.add_view(AdminUserAdmin)
    admin.add_view(ManualPaymentRequestAdmin)
    admin.add_view(PaymentAttemptAdmin)
    # Mock UI только при sandbox + флаге (маршрут сам отдаёт 404 иначе).
    if settings.payments_sandbox_mode and settings.payments_mock_ui:
        admin.add_view(PaymentAttemptMockView)
    admin.add_view(PaymentReviewView)
    admin.add_view(OperatorView)
    return admin
