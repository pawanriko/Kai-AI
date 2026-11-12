"""`python manage.py check_catalogue` — validate the picker model ids
against each provider's live models list (Phase 3).

Dead ids are printed as warnings and make the command exit 1 (via
CommandError, the standard "check failed" signal) so a cron can
notice. Providers that cannot be reached, or have no key, are
reported "unchecked" — never "dead" — and do not fail the command.
Nothing here changes the catalogue or touches chat: a failed check
is information, never an outage.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from chat import catalogue
from chat.ai import PROVIDERS


class Command(BaseCommand):
    help = "Check the model catalogue against providers' live lists."

    def handle(self, *args, **options):
        any_dead = False
        for provider, cfg in PROVIDERS.items():
            catalogue_ids = [mid for mid, _ in cfg["models"]]
            verdict = catalogue.check_provider(
                provider, catalogue_ids, os.environ.get(cfg["key_env"], "")
            )
            status = verdict["status"]
            if status == "unchecked":
                self.stdout.write(
                    f"{provider}: unchecked ({verdict['reason']})"
                )
            elif status == "ok":
                self.stdout.write(
                    f"{provider}: ok "
                    f"({len(verdict['alive'])} models live)"
                )
            else:
                any_dead = True
                self.stderr.write(
                    f"WARNING {provider}: dead model ids: "
                    + ", ".join(verdict["dead"])
                )
                if verdict["alive"]:
                    self.stdout.write(
                        f"{provider}: {len(verdict['alive'])} models live"
                    )
        if any_dead:
            raise CommandError(
                "Catalogue contains dead model ids (see warnings above). "
                "Remove or replace them; chat itself is unaffected."
            )
        self.stdout.write("Catalogue check complete.")
