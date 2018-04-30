import logging

from citation.models import Publication, ModelDocumentation, PublicationModelDocumentations, AuditCommand
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Publication, dispatch_uid='model_doc_source_code_sync')
def sync_model_documentation(sender, instance: Publication, **kwargs):
    """
    Ensures that when url is mentioned in publication then model documentation has source code value present in it
    """
    model_documentation = ModelDocumentation.objects.get(name='Source code')
    records = PublicationModelDocumentations.objects.filter(publication=instance.id,
                                                           model_documentation=model_documentation).count()
    if instance.code_archive_url.strip() is not '' and records < 1:
        creator = User.objects.get(username='alee14')
        audit_command = AuditCommand.objects.create(creator=creator,
                                                    action=AuditCommand.Action.MANUAL)
        PublicationModelDocumentations.objects.log_get_or_create(audit_command=audit_command, publication_id=instance.id,
                                                                 model_documentation_id=model_documentation.id)

    logger.info('Saved: {}'.format(instance.__dict__))

