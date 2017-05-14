from django.core.management.base import BaseCommand
from django.db.models import Count

from citation.models import Publication, Note, Platform, Sponsor

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Exports data to a csv file. '''

    def add_arguments(self, parser):
        parser.add_argument('--outfile',
                            default='data.csv',
                            help='exported csv outfile')

    def find_max(self, attribute):
        return Publication.objects.annotate(num=Count(attribute)).order_by('-num')[0].num

    def get_attribute_values(self, attributes):
        c = []
        for attr in attributes:
            c.append(str(attr[0]))
        return c

    def create_output(self, items, values):
        output = []
        for item in items:
            if item[0] in values:
                output.append(1)
            else:
                output.append(0)
        return output

    def handle(self, *args, **options):
        logger.debug("Starting to export data. Hang tight, this may take a while.")
        header = ["Count", "Id", "Publication Title", "Abstract", "Short Title", "Zotero Key", "Code Url",
                  "Date Published Text", "Date Accessed", "Archive", "Archive location", "Library catalog",
                  "Call number", "Rights", "Extra", "Published Language", "Date Added", "Date Modified",
                  "Zotero Date Added", "Zotero Date Modified", "Status", "Code Archive url", "Contact Email",
                  "Author Comments", "Email Sent out", "Added by", "Assign Curator", "Conatct Author Name",
                  "Resource type", "Is primary", "Journal Id", "doi", "Series text", "Series title", "Series", "Issue",
                  "Volume", "ISSN", "pages", "Year of Publication", "Journal", "Notes", "Platform List"]
        all_platforms = Platform.objects.all().values_list("name").order_by("name")
        all_sponsors = Sponsor.objects.all().values_list("name").order_by("name")
        header.extend(self.get_attribute_values(all_platforms))
        header.append("Sponsors List")
        header.extend(self.get_attribute_values(all_sponsors))
        publications = Publication.objects.filter(is_primary=True).prefetch_related('sponsors', 'platforms')
        COUNT = 1
        writer = options['outfile']
        writer.writerow(header)
        for pub in publications:
            platforms = self.get_attribute_values(list(pub.platforms.all().values_list("name")))
            sponsors = self.get_attribute_values(list(pub.sponsors.all().values_list("name")))
            notes = self.get_attribute_values(list(Note.objects.filter(publication=pub.pk).values_list("text")))

            platforms_output = self.create_output(all_platforms,platforms)
            sponsors_output = self.create_output(all_sponsors,sponsors)

            row = [COUNT, pub.pk, pub.title, str(pub.abstract), pub.short_title, pub.zotero_key, pub.url,
                   pub.date_published_text, pub.date_accessed, pub.archive, pub.archive_location,
                   pub.library_catalog,
                   pub.call_number, pub.rights, pub.extra, pub.published_language, pub.date_added,
                   pub.date_modified, pub.zotero_date_added, pub.zotero_date_modified, pub.status,
                   pub.code_archive_url, pub.contact_email, pub.author_comments,
                   pub.email_sent_count, pub.added_by, pub.assigned_curator, pub.contact_author_name,
                   pub.container.type, pub.is_primary, pub.container.id, pub.doi, pub.series_text,
                   pub.series_title, pub.series, pub.issue, pub.volume, pub.issn, pub.pages,
                   pub.container.date_added, pub.container.name, notes, platforms]
            row.extend(platforms_output)
            row.append(sponsors)
            row.extend(sponsors_output)
            writer.writerow(row)
            COUNT += 1

        logger.debug("Data export completed.")
        return writer