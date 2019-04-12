import csv

from citation.models import Publication, Platform, Sponsor

CSV_DEFAULT_HEADER = ["id", "title", "abstract", "short_title", "zotero_key", "url",
                      "date_published_text", "date_accessed", "archive", "archive_location",
                      "library_catalog", "call_number", "rights", "extra", "published_language", "date_added",
                      "date_modified", "zotero_date_added", "zotero_date_modified", "status", "code_archive_urls",
                      "contact_email", "author_comments", "email_sent_count", "added_by", "assigned_curator",
                      "contact_author_name", "is_primary", "doi", "series_text", "series_title", "series", "issue",
                      "volume", "issn", "pages", "container", "platforms", "sponsors"]

# Streaming CSV taken from
# https://docs.djangoproject.com/en/2.1/howto/outputting-csv/

class Echo:
    """An object that implements just the write method of the file-like
    interface.
    """
    def write(self, value):
        """Write the value by returning it, instead of storing in a buffer."""
        return value


class CategoricalVariable:
    def __init__(self, levels):
        self._levels = levels

    def dense_encode(self, values):
        return [(level in values) for level in self._levels]

    def __iter__(self):
        return iter(self._levels)


class PublicationCSVExporter:

    def __init__(self, attributes=None):
        self.m2m_attributes = [fields.name for fields in Publication._meta.many_to_many]
        self.platforms = CategoricalVariable(Platform.objects.all().values_list("name", flat=True).order_by("name"))
        self.sponsors = CategoricalVariable(Sponsor.objects.all().values_list("name", flat=True).order_by("name"))
        if attributes is None:
            self.attributes = CSV_DEFAULT_HEADER
        else:
            self.attributes = attributes

        self.verify_attributes()

    def verify_attributes(self):
        for name in self.attributes:
            if not hasattr(Publication, name):
                raise AttributeError("Publication model doesn't have attribute :" + name)

    def get_header(self):
        header = []

        for name in self.attributes:
            if name in self.m2m_attributes:
                header.append(name)
                header.extend(self.get_all_m2m_levels(name))
            else:
                header.append(name.strip().replace('_', ' '))
        return header

    def get_all_m2m_levels(self, name):
        if name in ['sponsors', 'platforms']:
            return getattr(self, name)
        else:
            raise AttributeError("Forgot to declare " + name + " m2m attribute")

    def get_row(self, pub):
        row = []
        for name in self.attributes:
            if name in self.m2m_attributes:
                source = getattr(pub, name)
                pub_m2m_data_list = source.all().values_list('name', flat=True)
                row.append(pub_m2m_data_list)
                row.extend(self.get_all_m2m_levels(name).dense_encode(pub_m2m_data_list))
            else:
                row.append(getattr(pub, name))
        return row

    def write_all(self, file):
        writer = csv.writer(file, delimiter=',')
        writer.writerow(self.get_header())
        publications = Publication.api.primary()
        for pub in publications:
            writer.writerow(self.get_row(pub))
        return writer

    def stream(self):
        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer, delimiter=',')
        writer.writerow(self.get_header())
        publications = Publication.api.primary()
        for pub in publications:
            yield writer.writerow(self.get_row(pub))
