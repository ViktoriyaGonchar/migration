"""
CLI для локальной проверки и ручной выдачи доступа (Phase 2A: grant-access / reissue-link).

Печать готовой ссылки — grant-access, reissue-link, legacy issue-login-token.
"""

from __future__ import annotations

import asyncio

import typer
from passlib.context import CryptContext

from app.config import get_settings
from app.db.models.admin_user import AdminUser
from app.db.models.subscriber import Subscriber
from app.db.session import async_session_maker
from app.services import access_issue
from app.services import telegram_linking

cli = typer.Typer(help="Утилиты Migration Compass (first pass + Phase 2A + Phase 3)")
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@cli.command("create-subscriber")
def create_subscriber(
    label: str | None = typer.Option(None, "--label", "-l", help="Внутренняя метка"),
) -> None:
    """Создаёт подписчика и печатает subscriber_id."""

    async def run() -> None:
        async with async_session_maker() as session:
            row = Subscriber(label=label)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            typer.echo(f"subscriber_id={row.id}")

    asyncio.run(run())


@cli.command("create-subscription")
def create_subscription(
    subscriber_id: int = typer.Option(..., help="ID подписчика"),
    days: int = typer.Option(30, help="Длительность в днях"),
) -> None:
    """Создаёт или продлевает подписку через общий сервис (без login token)."""

    async def run() -> None:
        async with async_session_maker() as session:
            try:
                sub, _kind = await access_issue.create_or_extend_subscription_only(
                    session,
                    subscriber_id,
                    days,
                    source=access_issue.CHANNEL_MANUAL_CLI,
                )
                await session.commit()
            except ValueError as e:
                typer.secho(str(e), err=True)
                raise typer.Exit(1) from e
            await session.refresh(sub)
            typer.echo(f"subscription_id={sub.id}")

    asyncio.run(run())


@cli.command("issue-login-token")
def issue_login_token(subscriber_id: int = typer.Option(..., help="ID подписчика")) -> None:
    """Legacy: только login token + URL, без проверки подписки и без audit."""

    async def run() -> None:
        settings = get_settings()
        async with async_session_maker() as session:
            url = await access_issue.legacy_issue_login_token_url(session, subscriber_id, settings)
            await session.commit()
        typer.echo(url)

    asyncio.run(run())


@cli.command("grant-access")
def grant_access(
    subscriber_id: int = typer.Option(..., help="ID подписчика"),
    days: int = typer.Option(..., help="Длительность в днях"),
) -> None:
    """Выдаёт или продлевает доступ на N дней и печатает готовую login-ссылку."""

    async def run() -> None:
        settings = get_settings()
        async with async_session_maker() as session:
            try:
                url = await access_issue.grant_access_for_days(session, subscriber_id, days, settings)
                await session.commit()
            except ValueError as e:
                typer.secho(str(e), err=True)
                raise typer.Exit(1) from e
        typer.echo(url)

    asyncio.run(run())


@cli.command("reissue-link")
def reissue_link(subscriber_id: int = typer.Option(..., help="ID подписчика")) -> None:
    """Новая login-ссылка при активной подписке; срок подписки не меняется."""

    async def run() -> None:
        settings = get_settings()
        async with async_session_maker() as session:
            try:
                url = await access_issue.reissue_login_link(session, subscriber_id, settings)
                await session.commit()
            except ValueError as e:
                typer.secho(str(e), err=True)
                raise typer.Exit(1) from e
        typer.echo(url)

    asyncio.run(run())


@cli.command("issue-telegram-link")
def issue_telegram_link(
    subscriber_id: int = typer.Option(..., "--subscriber-id", help="ID подписчика"),
    ttl_hours: int = typer.Option(72, "--ttl-hours", help="Срок жизни токена в часах"),
) -> None:
    """Выдаёт одноразовую ссылку t.me/...?start=... для привязки Telegram (старые pending токены снимаются)."""

    async def run() -> None:
        settings = get_settings()
        if not settings.bot_username:
            typer.secho(
                "Задайте BOT_USERNAME в .env (username бота без @, для deep link).",
                err=True,
            )
            raise typer.Exit(1)
        async with async_session_maker() as session:
            try:
                raw = await telegram_linking.issue_telegram_link_token(
                    session,
                    subscriber_id,
                    settings,
                    ttl_hours=ttl_hours,
                )
                await session.commit()
            except ValueError as e:
                await session.rollback()
                typer.secho(str(e), err=True)
                raise typer.Exit(1) from e
        url = f"https://t.me/{settings.bot_username}?start={raw}"
        typer.echo(url)

    asyncio.run(run())


@cli.command("unlink-telegram-subscriber")
def unlink_telegram_subscriber(
    subscriber_id: int = typer.Option(..., "--subscriber-id", help="ID подписчика"),
) -> None:
    """Снимает привязку Telegram у подписчика (подписки и сессии сайта не трогает)."""

    async def run() -> None:
        async with async_session_maker() as session:
            try:
                ok = await telegram_linking.unlink_subscriber(session, subscriber_id)
                await session.commit()
            except ValueError as e:
                await session.rollback()
                typer.secho(str(e), err=True)
                raise typer.Exit(1) from e
        if not ok:
            typer.secho("Привязка не найдена.", err=True)
            raise typer.Exit(1)
        typer.echo("Привязка снята.")

    asyncio.run(run())


@cli.command("unlink-telegram-user")
def unlink_telegram_user(
    telegram_user_id: int = typer.Option(..., "--telegram-user-id", help="Telegram user id"),
) -> None:
    """Снимает привязку по telegram_user_id."""

    async def run() -> None:
        async with async_session_maker() as session:
            ok = await telegram_linking.unlink_telegram_user(session, telegram_user_id)
            await session.commit()
        if not ok:
            typer.secho("Привязка не найдена.", err=True)
            raise typer.Exit(1)
        typer.echo("Привязка снята.")

    asyncio.run(run())


@cli.command("create-admin")
def create_admin(
    email: str = typer.Option(..., help="Email входа в /admin"),
    password: str = typer.Option(..., help="Пароль"),
) -> None:
    """Создаёт запись admin_users (нужна до первого входа в SQLAdmin)."""

    async def run() -> None:
        async with async_session_maker() as session:
            row = AdminUser(email=email, password_hash=_pwd.hash(password))
            session.add(row)
            await session.commit()
            await session.refresh(row)
            typer.echo(f"admin_id={row.id} email={row.email}")

    asyncio.run(run())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
