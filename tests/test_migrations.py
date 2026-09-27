from importlib import import_module
from unittest import mock

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

backfill_migration = import_module(
    "citation.migrations.0038_backfill_publication_year_published"
)

BEFORE_BACKFILL = [("citation", "0037_publication_year_published")]
AFTER_BACKFILL = [("citation", "0038_backfill_publication_year_published")]


class BackfillYearPublishedMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(AFTER_BACKFILL)

    def test_backfills_years_across_batches(self):
        apps = self.migrate(BEFORE_BACKFILL)
        user = apps.get_model("auth", "User").objects.create(username="backfill-user")
        container = apps.get_model("citation", "Container").objects.create(
            name="Backfill Journal"
        )
        Publication = apps.get_model("citation", "Publication")
        expected = {
            "2019": 2019,
            "JUN 2014": 2014,
            "SEP-OCT 2007": 2007,
            "": None,
            "n.d.": None,
        }
        for index, date_published_text in enumerate(expected):
            # historical models bypass Publication.save(), so year_published stays empty
            Publication.objects.create(
                title=f"Publication {index}",
                date_published_text=date_published_text,
                added_by_id=user.pk,
                container_id=container.pk,
            )

        with mock.patch.object(backfill_migration, "BATCH_SIZE", 2):
            apps = self.migrate(AFTER_BACKFILL)

        years = dict(
            apps.get_model("citation", "Publication").objects.values_list(
                "date_published_text", "year_published"
            )
        )
        self.assertEqual(years, expected)
