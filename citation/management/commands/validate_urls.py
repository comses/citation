import logging

from citation.ping_urls import verify_url_status
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Method that check if the code archived urls are active and working or not '''

    def handle(self, *args, **options):
        verify_url_status()

    logger.debug("Validation completed")
