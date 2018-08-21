import logging

from citation.export_data import PublicationCSVExporter
from django.core.management.base import BaseCommand

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
            publication_csv_exporter = PublicationCSVExporter(header)
        else:
            publication_csv_exporter = PublicationCSVExporter()
        with open(filename, 'w', encoding="utf-8") as csvfile:
            publication_csv_exporter.write_all(csvfile)

        logger.debug("Data export completed.")
