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
    has_source_code_model_documentation = PublicationModelDocumentations.objects.filter(
        publication=instance.id, model_documentation=model_documentation).exists()

    default_submitter = User.objects.filter(is_active=True).first()
    for code_archive_url in instance.code_archive_urls.all():
        if code_archive_url.is_available and not has_source_code_model_documentation:
            audit_command = AuditCommand.objects.create(creator=default_submitter,
                                                        action=AuditCommand.Action.MANUAL)
            PublicationModelDocumentations.objects.log_get_or_create(audit_command=audit_command,
                                                                     publication_id=instance.id,
                                                                     model_documentation_id=model_documentation.id)
            logger.info("syncing model documentation: source code for updated code archive url on %s", instance)
            # only need to do this once
            return

    if has_source_code_model_documentation:
        # degenerate data, no code archive url associated with this Publication and yet it has been marked as having
        # source code model documentation. Flag it.
        instance.flag('Source code model documentation specified on this publication but no valid code archive urls were found',
                      default_submitter)
