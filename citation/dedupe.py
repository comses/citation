import ast
import logging

from django.db import transaction

from . import models

logger = logging.getLogger(__name__)


class DataProcessor(object):

    def __init__(self, model, creator):
        self.model = model
        self.through_model = model.publications.through
        self.through_field = model.publications.field.name
        self.through_id_name = model.publications.field.m2m_reverse_name()
        self.creator = creator

    def execute(self, action, path):
        with transaction.atomic():
            if action == '.merge':
                self.merge(path)
            elif action == '.split':
                self.split(path)
            elif action == '.delete':
                self.delete(path)
            elif action == '.insert':
                self.insert(path)
            else:
                raise ValueError("Invalid action extension {0}. Must be '.merge' or '.split'".format(action))

    def insert(self, path):
        with open(path, "r") as f:
            names = ast.literal_eval(f.read())
            audit_command = models.AuditCommand.objects.create(action=models.AuditCommand.Action.MANUAL,
                                                               creator=self.creator)
            for name in names:
                self.model.objects.log_create(audit_command=audit_command, name=name)

    def delete(self, path):
        with open(path, "r") as f:
            names = ast.literal_eval(f.read())
            audit_command = models.AuditCommand.objects.create(action=models.AuditCommand.Action.MANUAL,
                                                               creator=self.creator)
            self.model.objects.filter(name__in=names).log_delete(audit_command=audit_command)

    def split(self, path):
        with open(path, "r") as f:
            splits = ast.literal_eval(f.read())
            for name, new_names in splits:
                logger.debug("Splitting %s into %s", name, new_names)
                self.split_record(name=name, new_names=new_names)

    def merge(self, path):
        with open(path, "r") as f:
            merges = ast.literal_eval(f.read())
            for names, new_name in merges:
                self.merge_records(names=names, new_name=new_name)

    def split_record(self, name, new_names):
        """
        Takes a single value name and splits it into multiple values denoted by the new_names list.
        """
        with transaction.atomic():
            audit_command = models.AuditCommand.objects.create(action=models.AuditCommand.Action.SPLIT,
                                                               creator=self.creator)
            through_model = self.through_model
            record = self.model.objects.prefetch_related('publications').get(name=name)
            publications = record.publications.all()
            record.log_delete(audit_command=audit_command)
            new_records = [self.model.objects.log_get_or_create(audit_command=audit_command,
                                                                name=new_name)[0] for new_name in new_names]
            for publication in publications:
                for new_record in new_records:
                    through_model.objects.log_get_or_create(
                        audit_command=audit_command,
                        **{'publication_id': publication.id, self.through_id_name: new_record.id})

    def get_related_publications_with_name(self, names):
        criteria = {'{0}__name__in'.format(self.through_field): names}
        return list(models.Publication.objects.filter(**criteria))

    def merge_records(self, names, new_name):
        with transaction.atomic():
            audit_command = models.AuditCommand.objects.create(creator=self.creator,
                                                               action=models.AuditCommand.Action.MERGE)
            records_to_merge = self.model.objects.filter(name__in=names)
            # log the deleted records to merge and the record that will be replacing them
            publications = self.get_related_publications_with_name(names)
            canonical_record, created = self.model.objects.log_get_or_create(audit_command=audit_command,
                                                                             name=new_name)
            payload = {self.through_id_name: canonical_record.id}
            for publication in publications:
                payload['publication_id'] = publication.id
                self.through_model.objects.log_get_or_create(audit_command=audit_command,
                                                             **payload)
            records_to_merge.exclude(name=new_name).log_delete(audit_command=audit_command)
            return canonical_record
