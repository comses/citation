import logging
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

from citation import dedupe, models
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Removes orphans from Platform and Sponsors Table"

    def handle(self, *args, **options):
        qs = models.Platform.objects.exclude(pk__in=models.Publication.platforms.through.objects.values('platform'))
        qs.delete()

        qs = models.Sponsor.objects.exclude(pk__in=models.Publication.sponsors.through.objects.values('sponsor'))
        qs.delete()

        logger.debug("Orphans deleted successfully")
