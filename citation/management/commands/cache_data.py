import logging

from django.core.management.base import BaseCommand

from citation.caching import initialize_contributor_cache

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Method to cache the data '''

    def handle(self, *args, **options):
        initialize_contributor_cache()
