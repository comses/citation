from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models.functions import Lower

from ...merger import PublicationMergeGroup
from ...models import Publication, AuditCommand


class Command(BaseCommand):
    help = "Merge publications by doi"

    def add_arguments(self, parser):
        parser.add_argument('--creator',
                            required=True,
                            help="username of a User to be recorded in the audit log when executing these commands")

    def _get_duplicates(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT array_agg(id ORDER BY date_added, id)
                  FROM citation_publication
                  GROUP BY lower(doi)
                  HAVING count(lower(doi)) > 1;
                """
            )
            data = [r[0] for r in cursor.fetchall()]
            return data

    def merge_publications_by_doi(self, creator):
        duplicate_id_groups = self._get_duplicates()

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
        self.merge_publications_by_doi(creator)
        publication_mixed_case_dois = Publication.objects.exclude(doi__exact=Lower('doi')).exclude(doi__isnull=True)
        audit_command = AuditCommand(creator=creator, action='MANUAL')
        for publication in publication_mixed_case_dois:
            doi = publication.doi
            if doi:
                doi = doi.lower()
                Publication.objects.filter(id=publication.id).log_update(audit_command=audit_command, doi=doi)
