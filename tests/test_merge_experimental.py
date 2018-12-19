from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from citation.merger.experimental import *


class MergeSetTest(SimpleTestCase):
    def to_frozen(self, merger):
        return set(map(frozenset, merger.group_id_to_pks.values()))

    def test_merge_set(self):
        ms = MergeSet([1, 2])
        ms.update(MergeSet([5, 2]))
        self.assertEqual(ms.items, [1, 5, 2])

    def test_distinct_union_set(self):
        self.assertEqual(self.to_frozen(DisjointUnionSet.from_items(
            [MergeSet([1, 2]), MergeSet([2, 3]), MergeSet([4, 5])])),
            {frozenset([1, 2, 3]), frozenset([4, 5])})
        self.assertEqual(self.to_frozen(DisjointUnionSet.from_items([{1, 2}, {3, 4}])),
                         {frozenset([1, 2]), frozenset([3, 4])})
        self.assertEqual(self.to_frozen(
            DisjointUnionSet.from_items([{1, 2}, {2, 3}, {3, 4}])),
            {frozenset([1, 2, 3, 4]), })


class AuthorMergeByNameTest(TestCase):
    def setUp(self):
        super().setUp()
        self.frank1 = Author.objects.create(given_name='Frank', family_name='Bob')
        self.frank2 = Author.objects.create(given_name='Frank', family_name='Bob')
        self.creator = User.objects.create(username='frank', email='a@b.com', first_name='Frank', last_name='Bob')

    def test_simple_merge_by_name(self):
        merge_authors_by_name(self.creator)
        self.assertEqual(Author.objects.count(), 1)

    def test_merge_by_name_with_aliases(self):
        author_aliases = [AuthorAlias(given_name='F', family_name='Bob', author=self.frank1),
                          AuthorAlias(given_name='FA', family_name='Bob', author=self.frank1),
                          AuthorAlias(given_name='F', family_name='Bob', author=self.frank2)]
        AuthorAlias.objects.bulk_create(author_aliases)
        merge_authors_by_name(self.creator)

        self.assertEqual(Author.objects.count(), 1)
        self.assertEqual(self.frank1.author_aliases.count(), 2)
        self.assertEqual(Author.objects.filter(id=self.frank2.id).first(), None)

    def test_merge_multiple_groups(self):
        beths = [Author(given_name='Beth', family_name='Bob'),
                 Author(given_name='Beth', family_name='bOB')]
        collin = Author.objects.create(given_name='Collin', family_name='Bob')
        Author.objects.bulk_create(beths)
        merge_authors_by_name(self.creator)

        self.assertEqual(Author.objects.filter(id=collin.id).count(), 1)
        self.assertEqual(Author.objects.filter(given_name='Frank', family_name='Bob').count(), 1)
        self.assertEqual(Author.objects.filter(given_name='Beth', family_name='Bob').count(), 1)
        self.assertEqual(Author.objects.filter(given_name='Beth', family_name='bOB').count(), 0)
