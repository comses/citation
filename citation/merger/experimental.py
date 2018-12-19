import logging
import itertools
from pprint import pformat
from typing import Dict, List

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Lower
from django_bulk_update.helper import bulk_update

from citation.merger import MergeError
from citation.models import Author, PublicationAuthors, AuthorAlias, RawAuthors, make_versioned_payload, AuditLog, \
    make_payload, AuditCommand, Publication

logger = logging.getLogger(__name__)


class MergeSet:
    def __init__(self, items):
        self.items: List = items
        self.item_set = set(items)

    def __iter__(self):
        return iter(self.items)

    def copy(self):
        return MergeSet(self.items.copy())

    def update(self, other):
        items = self.items
        self.items = []
        self.item_set = set()
        for (fst, snd) in itertools.zip_longest(items, other.items):
            if fst is not None and fst not in self.item_set:
                self.items.append(fst)
                self.item_set.add(fst)
            if snd is not None and snd not in self.item_set:
                self.items.append(snd)
                self.item_set.add(snd)

    def __getitem__(self, i):
        return self.items[i]

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, repr(self.items))


class DisjointUnionSet:
    """
    A set of sets than can have no overlapping sets.

    Adding a set that overlaps with an existing set results in unioning in removing the existing overlapping sets and
    adding new set that is the union of the overlapping sets and the set you wanted to add
    """

    def __init__(self):
        self.group_id = 0
        self.group_id_to_pks: Dict[int, MergeSet] = {}
        self.pk_to_group_id: Dict[int, int] = {}

    def __iter__(self):
        return iter(self.group_id_to_pks.values())

    def __len__(self):
        return len(self.group_id_to_pks)

    def add(self, group: MergeSet):
        self.group_id_to_pks[self.group_id] = group
        for pk in group.copy():
            if pk in self.pk_to_group_id:
                group_id = self.pk_to_group_id.pop(pk)
                existing_group = self.group_id_to_pks.pop(group_id)
                group.update(existing_group)
            assert pk not in self.pk_to_group_id
            self.pk_to_group_id[pk] = self.group_id

        self.group_id += 1

    def get_kept_pk(self, pk):
        """Get the entities pk that will be kept after the merge given a pk part of the MergeSet"""
        group_id = self.pk_to_group_id[pk]
        group = self.group_id_to_pks[group_id]
        kept_pk = group[0]
        return kept_pk

    def update(self, other: 'DisjointUnionSet'):
        for group in other.group_id_to_pks.values():
            self.add(group)

    @classmethod
    def from_items(cls, groups):
        merger = cls()
        for group in groups:
            merger.add(group)
        return merger

    def __repr__(self):
        return "{}.from_items({})".format(self.__class__.__name__, [v for v in self.group_id_to_pks.values()])


class _Empty:
    def __len__(self):
        return 0

    def __bool__(self):
        return False

    def __eq__(self, other):
        if isinstance(other, _Empty):
            return True
        return False


empty = _Empty()


class AuthorCoalescer:
    def _max_str_len_agg(self, authors, attr):
        v = empty
        for author in authors:
            if len(v) < len(getattr(author, attr)):
                v = getattr(author, attr)
        return v

    def family_name(self, authors):
        return self._max_str_len_agg(authors, 'family_name')

    def given_name(self, authors):
        return self._max_str_len_agg(authors, 'given_name')

    def orcid(self, authors):
        orcids = set(a.orcid for a in authors if a.orcid is not None)
        if len(orcids) > 1:
            raise MergeError("More than ORCiD in a merge group\n{}".format(authors))
        return orcids.pop() if orcids else empty

    def calculate_changes(self, authors):
        changes = {}
        for attr in ['family_name', 'given_name', 'orcid']:
            v = getattr(self, attr)(authors)
            if v != empty:
                changes[attr] = v
        return changes


class AuthorMerges:
    def __init__(self):
        self.coalescer = AuthorCoalescer()
        self.author_alias_creates = []
        self.author_updates = []
        self.author_deletes = []
        self.raw_author_updates = []
        self.raw_author_deletes = []
        self.author_alias_updates = []
        self.author_alias_deletes = []
        self.publication_author_updates = []

    def coalesce(self, authors):
        kept_author = authors[0]
        discarded_authors = authors[1:]
        changes = self.coalescer.calculate_changes(authors)
        return kept_author, changes, discarded_authors

    def add(self, merges: DisjointUnionSet):
        all_author_ids = list(itertools.chain.from_iterable(merges))
        all_authors = Author.objects.filter(id__in=all_author_ids).in_bulk()
        logger.debug('Author merges added : %s', pformat(all_authors))
        all_publication_authors = PublicationAuthors.objects.filter(author_id__in=all_author_ids)
        all_author_aliases = AuthorAlias.objects.filter(author_id__in=all_author_ids)
        all_raw_authors = RawAuthors.objects.filter(author_id__in=all_author_ids)

        for group in merges:
            author_ids = list(group)
            authors = [all_authors[author_id] for author_id in author_ids]
            kept_author, kept_author_updates, discarded_authors = self.coalesce(authors)
            self.author_updates.append((kept_author, kept_author_updates))
            self.author_deletes += discarded_authors

        for publication_author in all_publication_authors:
            kept_pk = merges.get_kept_pk(publication_author.author_id)
            if kept_pk != publication_author.author_id:
                self.publication_author_updates.append((publication_author, {'author_id': kept_pk}))

        #
        # Fixup RawAuthors
        #
        kept_raw_authors = []
        raw_author_updates = []
        for raw_author in all_raw_authors:
            kept_pk = merges.get_kept_pk(raw_author.author_id)
            if kept_pk != raw_author.author_id:
                raw_author_updates.append((raw_author, {'author_id': kept_pk}))
            else:
                kept_raw_authors.append(raw_author)

        # Discard raw authors that are listed
        kept_raw_author_raw_ids = frozenset(a.raw_id for a in kept_raw_authors)
        for (raw_author, changes) in raw_author_updates:
            if raw_author.raw_id in kept_raw_author_raw_ids:
                self.raw_author_deletes.append(raw_author)
            else:
                self.raw_author_updates.append((raw_author, changes))

        #
        # Fixup AuthorAlias
        #
        kept_author_aliases = []
        author_alias_updates = []
        for author_alias in all_author_aliases:
            kept_pk = merges.get_kept_pk(author_alias.author_id)
            if kept_pk != author_alias.author_id:
                author_alias_updates.append((author_alias, {'author_id': kept_pk}))
            else:
                kept_author_aliases.append(author_alias)

        # Discard author aliases that are listed
        kept_author_alias_names = frozenset((a.given_name, a.family_name) for a in kept_author_aliases)
        for (author_alias, changes) in author_alias_updates:
            if (author_alias.given_name, author_alias.family_name) in kept_author_alias_names:
                self.author_alias_deletes.append(author_alias)
            else:
                self.author_alias_updates.append((author_alias, changes))

    def _apply(self, instance, changes):
        for k, v in changes.items():
            setattr(instance, k, v)
        return instance

    def bulk_apply_updates(self, updates):
        instances = []
        for instance, changes in updates:
            self._apply(instance, changes)
            instances.append(instance)
        return instances

    def log_updates(self, audit_command, updates):
        audit_logs = []
        for (instance, changes) in updates:
            versioned_payload = make_versioned_payload(instance, changes)
            audit_logs.append(AuditLog(
                action='UPDATE',
                row_id=instance.id,
                table=instance._meta.model_name,
                payload=versioned_payload,
                audit_command=audit_command))
        return audit_logs

    def log_deletes(self, audit_command, deletes):
        audit_logs = []
        for instance in deletes:
            payload = make_payload(instance)
            audit_logs.append(AuditLog(
                action='DELETE',
                row_id=instance.id,
                table=instance._meta.model_name,
                payload=payload,
                audit_command=audit_command))
        return audit_logs

    def execute(self, creator):
        audit_command = AuditCommand.objects.create(action='MERGE', creator=creator, message='Bulk Merging Authors')
        # Add update logs
        audit_logs = self.log_updates(audit_command, self.author_updates)
        audit_logs += self.log_updates(audit_command, self.author_alias_updates)
        audit_logs += self.log_updates(audit_command, self.publication_author_updates)
        audit_logs += self.log_updates(audit_command, self.raw_author_updates)

        # Add delete logs
        audit_logs += self.log_deletes(audit_command, self.author_deletes)
        audit_logs += self.log_deletes(audit_command, self.author_alias_deletes)
        audit_logs += self.log_deletes(audit_command, self.raw_author_updates)

        AuditLog.objects.bulk_create(audit_logs)

        # Apply changes in an order that avoids foreign key constraint errors
        AuthorAlias.objects.filter(id__in=[a.id for a in self.author_alias_deletes]).delete()
        bulk_update(self.bulk_apply_updates(self.author_alias_updates))

        RawAuthors.objects.filter(id__in=[r.id for r in self.raw_author_deletes]).delete()
        bulk_update(self.bulk_apply_updates(self.raw_author_updates))

        bulk_update(self.bulk_apply_updates(self.publication_author_updates))

        Author.objects.filter(id__in=[r.id for r in self.author_deletes]).delete()
        bulk_update(self.bulk_apply_updates(self.author_updates))


# https://stackoverflow.com/questions/8991506/iterate-an-iterator-by-chunks-of-n-in-python
def grouper(n, iterable):
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, n))
        if not chunk:
            return
        yield chunk


def merge_authors_by_name(creator):
    with transaction.atomic():
        matchings = Author.objects \
            .filter(
            id__in=PublicationAuthors.objects \
                .filter(publication__in=Publication.api.primary()) \
                .values_list('author_id', flat=True)) \
            .exclude(family_name='') \
            .annotate(l_family_name=Lower('family_name'), l_given_name=Lower('given_name')) \
            .exclude(l_family_name='[anonymous]') \
            .values('l_family_name', 'l_given_name') \
            .annotate(author_count=Count('*')).filter(author_count__gt=1) \
            .annotate(author_ids=ArrayAgg('id')) \
            .order_by('-author_count')

        author_disjoint_union_set = DisjointUnionSet()
        for match in matchings:
            author_ids = MergeSet(sorted(match['author_ids']))
            author_disjoint_union_set.add(author_ids)

        chunked_disjoint_set = grouper(1, author_disjoint_union_set)
        ind = 0
        for chunk in chunked_disjoint_set:
            logger.info('Chunk # %i', ind)
            chunk_author_disjoint_union_set = DisjointUnionSet.from_items(chunk)
            author_merges = AuthorMerges()
            author_merges.add(chunk_author_disjoint_union_set)
            author_merges.execute(creator)
            ind += 1
