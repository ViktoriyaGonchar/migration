from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from access.services import create_access_token


class Command(BaseCommand):
    help = "Create development access token and print URL."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="", help="Optional email bound to token")
        parser.add_argument("--full-name", default="", help="Optional full name bound to token")
        parser.add_argument("--notes", default="Created by create_dev_token", help="Optional admin notes")
        parser.add_argument(
            "--save-file",
            action="store_true",
            help="Save token to .dev_token in project root",
        )

    def handle(self, *args, **options):
        token_obj = create_access_token(
            email=options["email"],
            full_name=options["full_name"],
            notes=options["notes"],
        )
        app_path = f"/app/?token={token_obj.token}"
        site_url = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
        app_url = app_path
        if site_url:
            app_url = f"{site_url}{app_path}"

        self.stdout.write(self.style.SUCCESS(f"Token: {token_obj.token}"))
        self.stdout.write(self.style.SUCCESS(f"URL: {app_url}"))

        if options["save_file"]:
            token_file = Path(settings.BASE_DIR) / ".dev_token"
            token_file.write_text(token_obj.token, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Saved to: {token_file}"))
