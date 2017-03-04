from django.core.management.base import BaseCommand
from django.db import connection
from ...merger import ContainerMergeGroup
from ...models import Container, AuditCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = "Merge containers by name"

    def add_arguments(self, parser):
        parser.add_argument('--creator',
                            required=True,
                            help="username of a User to be recorded in the audit log when executing these commands")

    def _get_duplicates(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """select array_agg(id order by date_added, id)
                from citation_container
                where name <> ''
                group by name
                having count(id) > 1;
                """
            )
            data = [r[0] for r in cursor.fetchall()]
            return data

    def merge_containers_by_name(self, creator):
        duplicate_id_groups = self._get_duplicates()

        print('container groups to merge', len(duplicate_id_groups))
        for (i, duplicate_id_group) in enumerate(duplicate_id_groups):
            containers = Container.objects.filter(id__in=duplicate_id_group).order_by('date_added')
            merge_group = ContainerMergeGroup.from_list(containers)
            audit_command = AuditCommand(creator=creator, action='MERGE')
            if merge_group.is_valid():
                merge_group.merge(audit_command)
            else:
                print(merge_group.errors)
            print('\tDone merger container group', i)

    def handle(self, *args, **options):
        creator = User.objects.get(username=options['creator'])
        self.merge_containers_by_name(creator)
