import csv
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase

from citation.export_data import PublicationCSVExporter
from citation.models import (
    Author,
    Container,
    Platform,
    Publication,
    PublicationAuthors,
    PublicationPlatforms,
    PublicationSponsors,
    Sponsor,
)


class PublicationCSVExporterTests(TestCase):
    # commas are intentional: exercises CSV field quoting/escaping
    PUBLICATION_TITLE = "Model, with comma"
    CONTAINER_NAME = "Journal, with comma"
    CONTAINER_ISSN = "1234-5678"
    AUTHORS = (("Ada", "Zephyr"), ("Grace", "Alpha"))
    EXPECTED_AUTHOR_NAMES = "Grace Alpha; Ada Zephyr"

    def setUp(self):
        self.user = User.objects.create_user(username="csv-export-user")
        self.container = Container.objects.create(
            name=self.CONTAINER_NAME,
            issn=self.CONTAINER_ISSN,
        )
        self.publication = self.create_publication(self.PUBLICATION_TITLE)
        for given_name, family_name in self.AUTHORS:
            author = Author.objects.create(
                given_name=given_name,
                family_name=family_name,
                type=Author.INDIVIDUAL,
            )
            PublicationAuthors.objects.create(
                publication=self.publication,
                author=author,
                role=PublicationAuthors.RoleChoices.AUTHOR,
            )

    def create_publication(self, title, **kwargs):
        return Publication.objects.create(
            title=title,
            date_published_text="2019",
            container=self.container,
            added_by=self.user,
            **kwargs,
        )

    def export_rows(self, exporter):
        output = StringIO()
        exporter.write_all(output)

        written = list(csv.reader(StringIO(output.getvalue())))
        streamed = list(csv.reader(StringIO("".join(exporter.stream()))))

        self.assertEqual(written, streamed)
        return written

    def test_rejects_nested_many_to_many_attribute_paths(self):
        self.assertTrue(PublicationCSVExporter.attribute_exists("platforms"))
        self.assertFalse(PublicationCSVExporter.attribute_exists("platforms__name"))

        with self.assertRaisesRegex(AttributeError, "platforms__name"):
            PublicationCSVExporter(attributes=["platforms__name"])

    def test_rejects_unsupported_many_to_many_attributes(self):
        for name in ("creators", "tags"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    AttributeError, f"Unsupported many-to-many attribute: {name}"
                ),
            ):
                PublicationCSVExporter(attributes=[name])

    def test_write_and_stream_keep_each_publication_in_one_csv_row(self):
        attributes = [
            "id",
            "title",
            "author_names",
            "container__issn",
            "container__name",
        ]

        rows = self.export_rows(PublicationCSVExporter(attributes=attributes))

        self.assertEqual(rows[0], attributes)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(len(row) == len(attributes) for row in rows))
        self.assertEqual(
            rows[1][1:],
            [
                self.PUBLICATION_TITLE,
                self.EXPECTED_AUTHOR_NAMES,
                self.CONTAINER_ISSN,
                self.CONTAINER_NAME,
            ],
        )

    def test_excludes_non_primary_publications(self):
        self.create_publication("Secondary citation", is_primary=False)

        rows = self.export_rows(PublicationCSVExporter(attributes=["title"]))

        self.assertEqual(rows[1:], [[self.PUBLICATION_TITLE]])

    def test_encodes_categorical_many_to_many_levels_as_columns(self):
        netlogo = Platform.objects.create(name="NetLogo")
        repast = Platform.objects.create(name="Repast")
        Platform.objects.create(name="MASON")
        for platform in (repast, netlogo):
            PublicationPlatforms.objects.create(
                publication=self.publication, platform=platform
            )
        PublicationSponsors.objects.create(
            publication=self.publication, sponsor=Sponsor.objects.create(name="NSF")
        )

        rows = self.export_rows(
            PublicationCSVExporter(attributes=["title", "platforms", "sponsors"])
        )

        self.assertEqual(
            rows[0],
            ["title", "platforms", "MASON", "NetLogo", "Repast", "sponsors", "NSF"],
        )
        self.assertEqual(
            rows[1],
            [
                self.PUBLICATION_TITLE,
                "NetLogo; Repast",
                "False",
                "True",
                "True",
                "NSF",
                "True",
            ],
        )

    def test_exports_every_primary_publication_in_id_order(self):
        second = self.create_publication("Second")
        third = self.create_publication("Third")
        PublicationPlatforms.objects.create(
            publication=second, platform=Platform.objects.create(name="NetLogo")
        )
        # the update moves the first row to the end of the table's physical order
        self.publication.abstract = "Updated abstract"
        self.publication.save()

        rows = self.export_rows(
            PublicationCSVExporter(
                attributes=["id", "title", "author_names", "platforms"]
            )
        )

        self.assertEqual(
            rows[0], ["id", "title", "author_names", "platforms", "NetLogo"]
        )
        self.assertEqual(
            rows[1:],
            [
                [
                    str(self.publication.pk),
                    self.PUBLICATION_TITLE,
                    self.EXPECTED_AUTHOR_NAMES,
                    "",
                    "False",
                ],
                [str(second.pk), "Second", "", "NetLogo", "True"],
                [str(third.pk), "Third", "", "", "False"],
            ],
        )

    def test_publication_without_authors_exports_an_empty_cell(self):
        PublicationAuthors.objects.filter(publication=self.publication).delete()

        rows = self.export_rows(
            PublicationCSVExporter(attributes=["title", "author_names"])
        )

        self.assertEqual(rows[1], [self.PUBLICATION_TITLE, ""])

    def test_quotes_embedded_newlines_and_quotes(self):
        abstract = 'First line\nSecond "quoted" line,\r\nthird line'
        self.publication.abstract = abstract
        self.publication.save()

        rows = self.export_rows(
            PublicationCSVExporter(attributes=["title", "abstract"])
        )

        self.assertEqual(rows[1], [self.PUBLICATION_TITLE, abstract])
