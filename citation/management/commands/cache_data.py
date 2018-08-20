import logging

from citation.caching import initialize_contributor_cache, initialize_publication_code_platform_cache, \
    initialize_network_cache
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Method to cache the data '''

    def add_arguments(self, parser):
        parser.add_argument('-c', '--contributor',
                            help='cache the contributor data')
        parser.add_argument('-p', '--publication',
                            help='caches the publication distribution data and code availability platform information for visualization')
        parser.add_argument('-n', '--network',
                            help='caches the network relation of publication')

    def handle(self, *args, **options):
        contributor = options.get('contributor')
        publication = options.get('publication')
        network = options.get('network')

        if not any([contributor, publication, network]):
            logger.info("No input specified on what to cache so caching everything")
            initialize_contributor_cache()
            initialize_publication_code_platform_cache()
            initialize_network_cache()

        if contributor:
            initialize_contributor_cache()
        elif publication:
            initialize_publication_code_platform_cache()
        elif network:
            initialize_network_cache()

    logger.debug("Cache Completed Successfully")
