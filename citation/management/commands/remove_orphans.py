import logging
from django.core.management.base import BaseCommand

from citation import dedupe, models
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Removes orphans from Platform and Sponsors Table"

    def handle(self, *args, **options):
        qs = models.Platform.objects.exclude(pk__in=models.Publication.platforms.through.objects.values('platform'))
        print("              -----------------------------------------------------------------           ")
        print("                    Following platform orphans has been deleted: "                         )
        print("              -----------------------------------------------------------------           ")
        for q in qs:
            print(q.name)
        print("Total platforms deleted: " + str(qs.count()))
        qs.delete()
        qs = models.Sponsor.objects.exclude(pk__in=models.Publication.sponsors.through.objects.values('sponsor'))
        print("              -----------------------------------------------------------------            ")
        print("                     Following sponsor orphans has been deleted:                           ")
        print("              -----------------------------------------------------------------            ")
        for q in qs:
            print(q.name)
        print("Total sponsors deleted: " + str(qs.count()))
        qs.delete()
        logger.debug("Orphans deleted successfully")
