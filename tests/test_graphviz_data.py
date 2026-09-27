from django.contrib.auth.models import User
from django.test import TestCase

from citation.graphviz.data import (
    filtered_publications,
    generate_aggregated_code_archived_platform_data,
    generate_aggregated_distribution_data,
)
from citation.models import (
    Author,
    CodeArchiveUrl,
    CodeArchiveUrlCategory,
    Container,
    Publication,
    PublicationAuthors,
)


def pks(publications):
    # a sorted list, unlike a set, exposes duplicate rows
    return sorted(publication.pk for publication in publications)


class GraphDataFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="graph-data-user")
        self.container = Container.objects.create(name="Graph Data Journal")
        self.ada = Author.objects.create(
            given_name="Ada",
            family_name="Modeler",
            type=Author.INDIVIDUAL,
        )
        self.grace = Author.objects.create(
            given_name="Grace",
            family_name="Researcher",
            type=Author.INDIVIDUAL,
        )
        self.in_range = self.create_publication("In range", "2019", self.ada)
        self.out_of_range = self.create_publication("Out of range", "2021", self.ada)
        self.in_range_other_author = self.create_publication(
            "In range, other author", "2019", self.grace
        )

    def create_publication(self, title, date_published_text, *authors):
        publication = Publication.objects.create(
            title=title,
            date_published_text=date_published_text,
            status=Publication.Status.REVIEWED,
            container=self.container,
            added_by=self.user,
        )
        for author in authors:
            PublicationAuthors.objects.create(
                publication=publication,
                author=author,
                role=PublicationAuthors.RoleChoices.AUTHOR,
            )
        return publication

    def test_filters_by_iso_year_without_mutating_input(self):
        criteria = {
            "is_primary": True,
            "status": Publication.Status.REVIEWED,
            "date_published__gte": "2019-01-01T00:00:00Z",
            "date_published__lte": "2019-12-31T00:00:00Z",
        }
        original_criteria = criteria.copy()

        publications = filtered_publications(criteria)
        distribution = generate_aggregated_distribution_data(
            criteria,
            classifier="general",
            name="Publications",
        )

        self.assertEqual(
            pks(publications),
            sorted([self.in_range.pk, self.in_range_other_author.pk]),
        )
        self.assertEqual(criteria, original_criteria)
        self.assertEqual(len(distribution), 1)
        self.assertEqual(distribution[0]["date"], 2019)
        self.assertEqual(distribution[0]["Code Not Available"], 2)

    def test_filters_by_author_without_mutating_input(self):
        criteria = {
            "is_primary": True,
            "status": Publication.Status.REVIEWED,
            "authors__name__exact": "Ada Modeler",
        }
        original_criteria = criteria.copy()

        publications = filtered_publications(criteria)

        self.assertEqual(
            pks(publications), sorted([self.in_range.pk, self.out_of_range.pk])
        )
        self.assertEqual(criteria, original_criteria)

    def test_filters_multi_author_publication_once_per_author(self):
        shared = self.create_publication("Shared", "2020", self.ada, self.grace)
        expected = {
            "Ada Modeler": [self.in_range.pk, self.out_of_range.pk, shared.pk],
            "Grace Researcher": [self.in_range_other_author.pk, shared.pk],
        }

        for author_name, expected_pks in expected.items():
            with self.subTest(author_name=author_name):
                publications = filtered_publications(
                    {"is_primary": True, "authors__name__exact": author_name}
                )

                self.assertEqual(pks(publications), sorted(expected_pks))

    def test_require_year_excludes_publications_without_year(self):
        no_year = self.create_publication("Unknown year", "", self.ada)
        criteria = {"is_primary": True, "status": Publication.Status.REVIEWED}

        self.assertIn(no_year.pk, pks(filtered_publications(criteria)))
        self.assertNotIn(
            no_year.pk, pks(filtered_publications(criteria, require_year=True))
        )

    def test_counts_current_archive_categories_for_matching_publications(self):
        category = CodeArchiveUrlCategory.objects.create(
            category="Archive",
            subcategory="Test archive",
        )
        CodeArchiveUrl.objects.create(
            publication=self.in_range,
            category=category,
            status=CodeArchiveUrl.STATUS.available,
            creator=self.user,
            url="https://example.com/model",
        )
        CodeArchiveUrl.objects.create(
            publication=self.out_of_range,
            category=category,
            status=CodeArchiveUrl.STATUS.available,
            creator=self.user,
            url="https://example.com/out-of-range-model",
        )

        counts = generate_aggregated_code_archived_platform_data(
            {
                "is_primary": True,
                "date_published__gte": "2019-01-01T00:00:00Z",
                "date_published__lte": "2019-12-31T00:00:00Z",
            }
        )

        self.assertEqual(counts["Archive"], 1)
        self.assertEqual(sum(counts.values()), 1)
