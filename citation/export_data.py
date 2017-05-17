from citation.models import Publication, Platform, Sponsor


# retrieves elements from tuple and append it to a list - for adding in csv row
def get_attribute_values(attributes):
    c = []
    for attr in attributes:
        c.append(str(attr[0]))
    return c


# creates a list of True/False depending whether values are within the items or not - for creating Matrix
def create_output(items, values):
    output = []
    for item in items:
        if item[0] in values:
            output.append(1)
        else:
            output.append(0)
    return output


def create_csv(writer):
    header = ["Count", "Id", "Publication Title", "Abstract", "Short Title", "Zotero Key", "Code Url",
              "Date Published Text", "Date Accessed", "Archive", "Archive location", "Library catalog",
              "Call number", "Rights", "Extra", "Published Language", "Date Added", "Date Modified",
              "Zotero Date Added", "Zotero Date Modified", "Status", "Code Archive url", "Contact Email",
              "Author Comments", "Email Sent out", "Added by", "Assign Curator", "Conatct Author Name",
              "Resource type", "Is primary", "Journal Id", "doi", "Series text", "Series title", "Series", "Issue",
              "Volume", "ISSN", "pages", "Year of Publication", "Journal", "Notes", "Platform List"]
    all_platforms = Platform.objects.all().values_list("name").order_by("name")
    all_sponsors = Sponsor.objects.all().values_list("name").order_by("name")
    header.extend(get_attribute_values(all_platforms))
    header.append("Sponsors List")
    header.extend(get_attribute_values(all_sponsors))
    publications = Publication.objects.filter(is_primary=True).prefetch_related('sponsors', 'platforms')
    count = 1
    writer.writerow(header)
    for pub in publications:
        platforms = get_attribute_values(list(pub.platforms.all().values_list("name")))
        sponsors = get_attribute_values(list(pub.sponsors.all().values_list("name")))
        notes = get_attribute_values(list(pub.note_set.all().values_list("text")))

        platforms_output = create_output(all_platforms, platforms)
        sponsors_output = create_output(all_sponsors, sponsors)

        row = [count, pub.pk, pub.title, str(pub.abstract), pub.short_title, pub.zotero_key, pub.url,
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
        count += 1

    return writer
