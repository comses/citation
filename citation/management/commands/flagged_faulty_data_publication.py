import logging

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from citation import models
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Flagging publication that doesnt have either of ODD or Other Narrative selected in model documentation"

    def handle(self, *args, **options):
        narrative_list = list()
        for category in models.ModelDocumentation.CATEGORIES:
            if category['category'] == 'Narrative':
                for name in category['modelDocumentationList']:
                    narrative_list.append(name['name'])

        total = models.Publication.api.primary(status='REVIEWED')
        difference = set(total).difference(
            set(models.Publication.api.primary(status="REVIEWED", model_documentation__name__in=narrative_list)))
        logger.debug("-------------------------Following publication contains faulty data -----------------------------")
        for pub in difference:
            try:
                creator = User.objects.get(username='alee14')
                audit_command = models.AuditCommand.objects.create(action=models.AuditCommand.Action.MANUAL,
                                                                   creator=creator)
                publication = models.Publication.objects.get(pk=pub.id)
                publication.log_update(audit_command, **{'flagged': True})

            except models.Publication.DoesNotExist:
                logger.debug(pub + "This publication doesnt exist anymore in the database")

        logger.debug("Publication with faulty data flagged successfully")