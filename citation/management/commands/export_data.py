from django.core.management.base import BaseCommand

from citation.export_data import create_csv

import csv
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Exports data to a csv file. '''

    def add_arguments(self, parser):
        parser.add_argument('--outfile',
                            default='data.csv',
                            help='exported csv outfile')

    def handle(self, *args, **options):
        filename = options['outfile']
        with open(filename, 'w', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile, delimiter=',')
            create_csv(writer=writer)
        logger.debug("Data export completed.")
