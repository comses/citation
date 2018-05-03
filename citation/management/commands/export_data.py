from django.core.management.base import BaseCommand

import csv
import logging

from citation.export_data import CsvGenerator

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Exports data to a csv file. '''

    def add_arguments(self, parser):
        parser.add_argument('--outfile',
                            default='data.csv',
                            help='exported csv outfile')
        parser.add_argument('--header',
                            default=None,
                            help="list of publication attributes name. e.g. ['id','title']")

    def handle(self, *args, **options):
        filename = options['outfile']
        if options.get('header') is not None:
            header = options.get('header').strip('[]').split(',')
            csv_generator = CsvGenerator(header)
        else:
            csv_generator = CsvGenerator()
        csv_data = csv_generator.create_csv_data()
        with open(filename, 'w', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile, delimiter=',')
            for row in csv_data:
                writer.writerow(row)
        logger.debug("Data export completed.")

