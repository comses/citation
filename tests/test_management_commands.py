from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from citation import models


class LoadBibtexCommandTest(TestCase):
    def test_handle_resolves_user_and_dispatches_file(self):
        user = models.User.objects.create_user(
            username="loader", email="loader@example.com", password="test"
        )
        command = __import__(
            "citation.management.commands.load_bibtex", fromlist=["Command"]
        ).Command()

        with TemporaryDirectory() as directory:
            filename = Path(directory) / "records.bib"
            filename.write_text("@article{record, title={Example}}")
            with patch.object(command, "process_bibtex_file") as process_file:
                command.handle(filename=str(filename), username=user.username)

        process_file.assert_called_once_with(filename, user)


class CleanDataCommandTest(TestCase):
    @patch("citation.management.commands.clean_data.dedupe.DataProcessor")
    def test_handle_dispatches_file_to_data_processor(self, processor_class):
        user = models.User.objects.create_user(
            username="cleaner", email="cleaner@example.com", password="test"
        )
        processor = processor_class.return_value

        call_command(
            "clean_data",
            file="platform.merge",
            creator=user.username,
        )

        processor_class.assert_called_once_with(models.Platform, user)
        processor.execute.assert_called_once_with(".merge", "platform.merge")


class RemoveOrphansCommandTest(TestCase):
    def test_handle_removes_unlinked_platforms_and_sponsors(self):
        user = models.User.objects.create_user(
            username="owner", email="owner@example.com", password="test"
        )
        container = models.Container.objects.create(name="Journal")
        publication = models.Publication.objects.create(
            title="Publication", added_by=user, container=container
        )
        linked_platform = models.Platform.objects.create(name="Linked platform")
        orphan_platform = models.Platform.objects.create(name="Orphan platform")
        linked_sponsor = models.Sponsor.objects.create(name="Linked sponsor")
        orphan_sponsor = models.Sponsor.objects.create(name="Orphan sponsor")
        models.PublicationPlatforms.objects.create(
            publication=publication, platform=linked_platform
        )
        models.PublicationSponsors.objects.create(
            publication=publication, sponsor=linked_sponsor
        )

        call_command("remove_orphans")

        self.assertTrue(models.Platform.objects.filter(pk=linked_platform.pk).exists())
        self.assertFalse(models.Platform.objects.filter(pk=orphan_platform.pk).exists())
        self.assertTrue(models.Sponsor.objects.filter(pk=linked_sponsor.pk).exists())
        self.assertFalse(models.Sponsor.objects.filter(pk=orphan_sponsor.pk).exists())
