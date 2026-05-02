"""
Очередь и разбор заявок на ручную оплату (Phase 6): approve/reject без выдачи доступа.
Phase 8A: фильтры, сводка, CSV (без review_note), runbook в шаблоне.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from sqladmin import BaseView, expose
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.config import get_settings
from app.db.models.manual_payment_request import ManualPaymentRequest
from app.db.session import async_session_maker
from app.services import manual_payment_requests as mpr_service
from app.util.timeutil import as_utc

_log = logging.getLogger(__name__)


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _queue_query_dict(request: Request) -> dict[str, str]:
    """Параметры списка для ссылок и CSV (только непустые значения кроме defaults)."""
    status = (request.query_params.get("status") or "").strip().lower()
    q = (request.query_params.get("q") or "").strip()
    sort = (request.query_params.get("sort") or "").strip().lower()
    d: dict[str, str] = {}
    if status and status != mpr_service.QUEUE_STATUS_PENDING:
        d["status"] = status
    if q:
        d["q"] = q
    if sort in ("asc", "old"):
        d["sort"] = "asc"
    return d


def _queue_query_string(request: Request) -> str:
    parts = _queue_query_dict(request)
    if not parts:
        return ""
    return "?" + urlencode(parts)


def _csv_href(request: Request) -> str:
    """Ссылка на выгрузку CSV с теми же фильтрами, что у списка."""
    parts = dict(_queue_query_dict(request))
    parts["format"] = "csv"
    return "?" + urlencode(parts)


def _detail_extra_query(request: Request) -> str:
    """Строка query без ведущего ? для дописывания к ?id= в шаблоне."""
    return urlencode(_queue_query_dict(request))


def _redirect_url_after_review(request: Request, request_id: int, form: Any) -> str:
    """URL 303 после approve/reject: id + ok + те же фильтры, что были на карточке (скрытые поля формы)."""
    params: dict[str, str] = {"id": str(request_id), "ok": "1"}
    st = str(form.get("retain_status") or "").strip().lower()
    q = str(form.get("retain_q") or "").strip()
    sort = str(form.get("retain_sort") or "").strip().lower()

    if st in (
        mpr_service.QUEUE_STATUS_APPROVED,
        mpr_service.QUEUE_STATUS_REJECTED,
        mpr_service.QUEUE_STATUS_ALL,
    ):
        params["status"] = st
    if q:
        params["q"] = q
    if sort == "asc":
        params["sort"] = "asc"

    return f"{request.url.path}?{urlencode(params)}"


class PaymentReviewView(BaseView):
    """Список заявок и карточка; выдача доступа — отдельно на странице Оператор."""

    name = "Оплата: очередь"
    name_plural = "Оплата: очередь"
    icon = "fa-solid fa-receipt"

    @expose("/payment-requests", methods=["GET", "POST"], identity="payment_requests")
    async def payment_requests_page(self, request: Request):
        title = "Заявки на ручную оплату"
        subtitle = "Одобрение или отклонение не выдаёт доступ — затем откройте страницу Оператор."
        error_message: str | None = None
        result_success: str | None = None
        redirect_response: RedirectResponse | None = None
        admin_user_id = request.session.get("admin_user_id")
        if admin_user_id is None:
            error_message = "Нет сессии администратора. Войдите в админку."

        list_rows: list[ManualPaymentRequest] = []
        detail: ManualPaymentRequest | None = None
        detail_id = _parse_int(request.query_params.get("id"))
        summary: mpr_service.ManualPaymentQueueSummary | None = None

        status_filter = mpr_service.normalize_queue_status_filter(
            request.query_params.get("status")
        )
        sort_desc = mpr_service.parse_queue_sort_desc(request.query_params.get("sort"))
        q_raw = (request.query_params.get("q") or "").strip()
        q_int = mpr_service.parse_queue_search_int(request.query_params.get("q"))
        # Нечисловой q не участвует в фильтре — подсказка в шаблоне.
        q_non_numeric_hint = bool(q_raw) and q_int is None
        settings = get_settings()
        list_query_suffix = _queue_query_string(request)
        csv_href = _csv_href(request)
        detail_extra_query = _detail_extra_query(request)

        if error_message is None:
            async with async_session_maker() as session:
                if request.method == "GET" and request.query_params.get("format") == "csv":
                    rows = await mpr_service.list_manual_payment_requests_filtered(
                        session,
                        status=status_filter,
                        q_int=q_int,
                        sort_desc=sort_desc,
                        limit=mpr_service.QUEUE_CSV_EXPORT_LIMIT,
                    )
                    await session.commit()
                    buf = io.StringIO()
                    w = csv.writer(buf)
                    # Заголовки: *_utc — моменты времени в UTC (ISO-8601), без локальной зоны.
                    w.writerow(
                        [
                            "id",
                            "created_at_utc_iso8601",
                            "status",
                            "telegram_user_id",
                            "subscriber_id",
                            "amount_label_snapshot",
                            "reviewed_at_utc_iso8601",
                            "reviewed_by_admin_id",
                        ]
                    )
                    for row in rows:
                        w.writerow(
                            [
                                row.id,
                                as_utc(row.created_at).isoformat(),
                                row.status,
                                row.telegram_user_id,
                                row.subscriber_id if row.subscriber_id is not None else "",
                                row.amount_label_snapshot or "",
                                as_utc(row.reviewed_at).isoformat() if row.reviewed_at else "",
                                row.reviewed_by_admin_id if row.reviewed_by_admin_id is not None else "",
                            ]
                        )
                    return Response(
                        content=buf.getvalue().encode("utf-8"),
                        media_type="text/csv; charset=utf-8",
                        headers={
                            "Content-Disposition": 'attachment; filename="manual_payment_requests_utc.csv"'
                        },
                    )

                if request.method == "POST":
                    form = await request.form()
                    action = str(form.get("action") or "").strip()
                    rid = _parse_int(form.get("request_id"))
                    note_raw = str(form.get("review_note") or "")
                    if rid is None:
                        error_message = "Не указана заявка."
                    elif action not in ("approve", "reject"):
                        error_message = "Неизвестное действие."
                    else:
                        try:
                            aid = int(admin_user_id)
                            if action == "approve":
                                await mpr_service.approve_manual_payment_request(
                                    session,
                                    request_id=rid,
                                    admin_user_id=aid,
                                    review_note=note_raw or None,
                                )
                            else:
                                await mpr_service.reject_manual_payment_request(
                                    session,
                                    request_id=rid,
                                    admin_user_id=aid,
                                    review_note=note_raw or None,
                                )
                            await session.commit()
                            redirect_response = RedirectResponse(
                                _redirect_url_after_review(request, rid, form),
                                status_code=303,
                            )
                        except ValueError as e:
                            await session.rollback()
                            error_message = str(e)
                            detail_id = rid
                        except Exception:
                            await session.rollback()
                            _log.exception("payment_requests_page")
                            error_message = "Операция не выполнена. Попробуйте снова."
                            detail_id = rid

                if redirect_response is not None:
                    return redirect_response

                summary = await mpr_service.manual_payment_queue_summary(session)

                if detail_id is not None:
                    detail = await session.get(ManualPaymentRequest, detail_id)
                    if detail is None and error_message is None:
                        error_message = "Заявка не найдена."

                list_rows = await mpr_service.list_manual_payment_requests_filtered(
                    session,
                    status=status_filter,
                    q_int=q_int,
                    sort_desc=sort_desc,
                    limit=mpr_service.QUEUE_PAGE_LIMIT_DEFAULT,
                )
                await session.commit()

        if (
            error_message is None
            and request.query_params.get("ok") == "1"
            and detail_id is not None
        ):
            result_success = (
                "Статус заявки сохранён. При одобрении выдайте доступ отдельно на странице Оператор."
            )

        stale_pending_alert = False
        if summary is not None and summary.oldest_pending_created_at is not None:
            now = datetime.now(timezone.utc)
            oc = as_utc(summary.oldest_pending_created_at)
            if now - oc > timedelta(hours=settings.stale_pending_alert_hours):
                stale_pending_alert = True

        context = {
            "request": request,
            "title": title,
            "subtitle": subtitle,
            "error_message": error_message,
            "result_success": result_success,
            "list_rows": list_rows,
            "detail": detail,
            "detail_id": detail_id,
            "as_utc": as_utc,
            "summary": summary,
            "filter_status": status_filter,
            "filter_q": q_raw,
            "filter_sort": "desc" if sort_desc else "asc",
            "list_query_suffix": list_query_suffix,
            "csv_href": csv_href,
            "detail_extra_query": detail_extra_query,
            "q_non_numeric_hint": q_non_numeric_hint,
            "stale_pending_alert": stale_pending_alert,
            "stale_pending_alert_hours": settings.stale_pending_alert_hours,
            "pending_triage_url": "/admin/payment-requests?status=pending&sort=asc",
        }
        return await self.templates.TemplateResponse(
            request,
            "admin/payment_requests.html",
            context,
        )
