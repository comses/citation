import logging
from django.core.management.base import BaseCommand

from citation import dedupe, models
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Removes orphans from Platform and Sponsors Table"

    def handle(self, *args, **options):
        qs = models.Platform.objects.exclude(pk__in=models.Publication.platforms.through.objects.values('platform'))
        logger.info("              -----------------------------------------------------------------           ")
        logger.info("                    Following platform orphans has been deleted: "                         )
        logger.info("              -----------------------------------------------------------------           ")
        name = []
        for q in qs:
            name.append(q.name)
        logger.info('\n'.join(name))
        logger.info("Total platforms deleted: " + str(qs.count()))
        qs.delete()
        qs = models.Sponsor.objects.exclude(pk__in=models.Publication.sponsors.through.objects.values('sponsor'))
        logger.info("              -----------------------------------------------------------------            ")
        logger.info("                     Following sponsor orphans has been deleted:                           ")
        logger.info("              -----------------------------------------------------------------            ")
        name = []
        for q in qs:
            name.append(q.name)
        logger.info('\n'.join(name))
        logger.info("Total sponsors deleted: " + str(qs.count()))
        qs.delete()
        logger.debug("Orphans deleted successfully")
