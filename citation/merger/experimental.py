import logging
import itertools
from datetime import datetime
from pprint import pformat
from typing import Dict, List

from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, Func
from django.db.models.functions import Lower, Substr
from django_bulk_update.helper import bulk_update

from citation.merger import MergeError
from citation.models import Author, PublicationAuthors, AuthorAlias, RawAuthors, make_versioned_payload, AuditLog, \
    make_payload, AuditCommand, Publication, SuggestedMerge, Submitter
from rest_framework import serializers

logger = logging.getLogger(__name__)


class MergeList:
    """"""
    def __init__(self, items, new_content=None):
        self.items: List = items
        self.item_set = set(items)

    def __iter__(self):
        return iter(self.items)

    def copy(self):
        return MergeList(self.items.copy())

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


class DisjointUnionList:
    """
    A set of sets than can have no overlapping sets.

    Adding a set that overlaps with an existing set results in unioning in removing the existing overlapping sets and
    adding new set that is the union of the overlapping sets and the set you wanted to add
    """

    def __init__(self):
        self.group_id = 0
        self.group_id_to_pks: Dict[int, MergeList] = {}
        self.pk_to_group_id: Dict[int, int] = {}

    def __iter__(self):
        return iter(self.group_id_to_pks.values())

    def __len__(self):
        return len(self.group_id_to_pks)

    def add(self, group: MergeList):
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

    def update(self, other: 'DisjointUnionList'):
        for group in other.group_id_to_pks.values():
            self.add(group)

    @classmethod
    def from_items(cls, groups):
        merger = cls()
        for group in groups:
            merger.add(group)
        return merger

    def to_suggested_merges(self, creator):
        coalescer = AutomaticAuthorCoalescer(creator=creator)
        all_author_pks = list(itertools.chain.from_iterable(self))
        all_authors = Author.objects.filter(id__in=all_author_pks).in_bulk()
        suggested_merges = []
        for merge_list in self:
            authors = [all_authors[pk] for pk in merge_list]
            suggested_merges.append(coalescer.coalesce(authors))
        return suggested_merges

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


class AutomaticAuthorCoalescer:
    def __init__(self, creator):
        self.creator = creator
        self.content_type = ContentType.objects.get_for_model(Author)

    def coalesce(self, authors):
        new_content = self.calculate_changes(authors)
        return SuggestedMerge(duplicates=sorted([a.pk for a in authors]), new_content=new_content,
                              content_type=self.content_type, creator=self.creator)

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

    def email(self, authors):
        v = empty
        first = authors[0]
        rest = authors[1:]
        if not first.email:
            for author in rest:
                if author.email:
                    v = author.email
        return v

    def calculate_changes(self, authors):
        changes = {}
        for attr in ['family_name', 'given_name', 'orcid', 'email']:
            v = getattr(self, attr)(authors)
            if v != empty:
                changes[attr] = v
        return changes


class OverlappingSuggestedMerge(serializers.ValidationError): pass


class AuthorMerges:
    def __init__(self):
        self.author_alias_creates = []
        self.author_updates = []
        self.author_deletes = []
        self.raw_author_updates = []
        self.raw_author_deletes = []
        self.author_alias_updates = []
        self.author_alias_deletes = []
        self.publication_author_updates = []

    @staticmethod
    def _create_kept_primary_key_resolver(suggested_merges):
        suggested_merge_lookup = {}
        content_pk_to_suggested_merge_pk = {}
        content_pk_to_kept_content_pk = {}
        for suggested_merge in suggested_merges:
            suggested_merge_lookup[suggested_merge.id] = suggested_merge
            for duplicate_pk in suggested_merge.duplicates:
                if duplicate_pk not in content_pk_to_suggested_merge_pk:
                    content_pk_to_suggested_merge_pk[duplicate_pk] = suggested_merge.id
                    content_pk_to_kept_content_pk[duplicate_pk] = suggested_merge.kept_pk
                else:
                    overlapping_suggested_merge_pks = [suggested_merge.id,
                                                       content_pk_to_suggested_merge_pk[duplicate_pk]]
                    overlapping_suggested_merges = [suggested_merge_lookup[pk] for pk in
                                                    overlapping_suggested_merge_pks]
                    raise OverlappingSuggestedMerge(
                        f'{overlapping_suggested_merges}. Please merge records before continuing')

        return content_pk_to_kept_content_pk

    def add(self, suggested_merges: List[SuggestedMerge]):
        all_author_pks = list(itertools.chain.from_iterable(sm.duplicates for sm in suggested_merges))
        all_authors = Author.objects.filter(id__in=all_author_pks).in_bulk()
        logger.debug('Author merges added : %s', pformat(all_authors))
        all_publication_authors = PublicationAuthors.objects.filter(author_id__in=all_author_pks)
        all_author_aliases = AuthorAlias.objects.filter(author_id__in=all_author_pks)
        all_raw_authors = RawAuthors.objects.filter(author_id__in=all_author_pks)
        kept_pk_resolver = self._create_kept_primary_key_resolver(suggested_merges)

        for suggested_merge in suggested_merges:
            kept_author = all_authors[suggested_merge.kept_pk]
            discarded_authors = [all_authors[pk] for pk in suggested_merge.discarded_pks]
            self.author_updates.append((kept_author, suggested_merge.new_content))
            self.author_deletes += discarded_authors

        for publication_author in all_publication_authors:
            kept_pk = kept_pk_resolver[publication_author.author_id]
            if kept_pk != publication_author.author_id:
                self.publication_author_updates.append((publication_author, {'author_id': kept_pk}))

        #
        # Fixup RawAuthors
        #
        kept_raw_authors = []
        raw_author_updates = []
        for raw_author in all_raw_authors:
            kept_pk = kept_pk_resolver[raw_author.author_id]
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
            kept_pk = kept_pk_resolver[author_alias.author_id]
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
        "Execute bulk author merges. Will have to rebuild search indices afterward"

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


def merge_authors_from_suggestedmerges(creator, qs=None):
    with transaction.atomic():
        if not qs:
            qs = SuggestedMerge.objects.all()
        qs = qs.filter(content_type=ContentType.objects.get_for_model(Author)).filter(date_applied__isnull=True)
        suggested_merges = list(qs)
        for suggested_merge in suggested_merges:
            logger.info('%s', suggested_merge)
            suggested_merge.duplicates = sorted(suggested_merge.duplicates)
            author_merges = AuthorMerges()
            author_merges.add([suggested_merge])
            author_merges.execute(creator)
        qs.update(date_applied=datetime.now())


def merge_authors_by_name(creator, only_primary=True):
    author_qs = Author.objects \
        .filter(
        id__in=PublicationAuthors.objects \
            .filter(publication__in=Publication.api.primary()) \
            .values_list('author_id', flat=True)) if only_primary else Author.objects.all()
    with transaction.atomic():
        matchings = author_qs \
            .exclude(family_name='') \
            .annotate(l_family_name=Lower('family_name'), l_given_name=Lower('given_name')) \
            .exclude(l_family_name='[anonymous]') \
            .values('l_family_name', 'l_given_name') \
            .annotate(author_count=Count('*')).filter(author_count__gt=1) \
            .annotate(author_ids=ArrayAgg('id')) \
            .order_by('-author_count')

        author_disjoint_union_set = DisjointUnionList()
        for match in matchings:
            author_ids = MergeList(sorted(match['author_ids']))
            author_disjoint_union_set.add(author_ids)

        submitter, created = Submitter.objects.get_or_create(user=creator)
        suggested_merges = author_disjoint_union_set.to_suggested_merges(submitter)
        SuggestedMerge.objects.bulk_create(suggested_merges)
        ind = 0
        for suggested_merge in suggested_merges:
            logger.info('Chunk # %i', ind)
            author_merges = AuthorMerges()
            author_merges.add([suggested_merge])
            author_merges.execute(creator)
            ind += 1
