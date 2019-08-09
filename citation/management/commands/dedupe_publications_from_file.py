import ast
import itertools

from django.contrib.auth.models import User
from django.db import transaction
from django.core.management.base import BaseCommand

from ...merger import PublicationMergeGroup
from ...models import Publication, AuditCommand


class Command(BaseCommand):
    help = "Merge publications by doi"

    def add_arguments(self, parser):
        parser.add_argument('--creator',
                            required=True,
                            help="username of a User to be recorded in the audit log when executing these commands")
        parser.add_argument('--file',
                            required=True,
                            help="file with groups of publication ids to merge as python List[List[int]] literal")

    def merge_publications(self, creator, duplicate_id_groups):
        with transaction.atomic():
            print('publication groups to merge', len(duplicate_id_groups))
            for (i, duplicate_id_group) in enumerate(duplicate_id_groups):
                publications = Publication.objects.filter(id__in=duplicate_id_group).order_by('date_added')
                merge_group = PublicationMergeGroup.from_list(list(publications))
                audit_command = AuditCommand(creator=creator, action='MERGE')
                if merge_group.is_valid():
                    merge_group.merge(audit_command)
                else:
                    print(merge_group.errors)
                print('\tDone merger publication group', i)

    def handle(self, *args, **options):
        creator = User.objects.get(username=options['creator'])
        with open(options['file'], 'r') as f:
            duplicate_id_groups = ast.literal_eval(f.read())
        self.merge_publications(creator, duplicate_id_groups)
        flagged_publications = Publication.objects.filter(
            id__in=list(itertools.chain.from_iterable(duplicate_id_groups)))
        audit_command = AuditCommand(creator=creator, action='MANUAL')
        for publication in flagged_publications:
            if publication.flagged:
                publication.log_update(audit_command, flagged=False)
