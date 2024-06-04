import csv

from citation.models import Publication, Platform, Sponsor


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


import numpy as np
import pandas as pd
import pathlib

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import models
from django.db.models import F, Count, Q, Value, Sum, OuterRef
from django.db.models.functions import Concat

from citation.models import Publication, Platform, Sponsor, PublicationCitations, PublicationAuthors, Author, \
    CodeArchiveUrl, PublicationPlatforms, PublicationSponsors, PublicationModelDocumentations, ModelDocumentation

CSV_DEFAULT_HEADER = ["id", "title", "abstract", "short_title", "contact_email", "email_sent_count",
                      "contact_author_name", "is_primary", "doi",
                      "series_text", "series_title", "series", "issue", "volume", "pages", "author_names",
                      "container__issn", "container__name", "year_published"]


def get_queryset():
    return Publication.api.primary().reviewed()


def get_publication_network(publications):
    data = PublicationCitations.objects \
        .filter(publication__in=publications, citation__in=publications) \
        .values('publication_id', 'citation_id')
    return pd.DataFrame.from_records(data)


class SumSubquery(models.Subquery):
    template = "(SELECT sum(subcount) from (%(subquery)s) _sum)"
    output_field = models.IntegerField()


def get_authors(publications):
    publication_authors = PublicationAuthors.objects \
        .filter(publication__in=publications) \
        .values('publication_id', 'author_id')
    cite = Publication.api.primary().reviewed() \
        .annotate(subcount=Count('referenced_by', filter=Q(is_primary=True) & Q(status='REVIEWED'))) \
        .filter(creators=OuterRef('pk')).values('subcount')
    p_tot = Publication.api.primary().reviewed() \
        .filter(creators=OuterRef('pk')) \
        .annotate(subcount=models.Value(1, output_field=models.IntegerField())).values('subcount')
    p_avail = Publication.api.primary().reviewed() \
        .with_code_availability_counts().filter(has_available_code=True) \
        .filter(creators=OuterRef('pk')) \
        .annotate(subcount=models.Value(1, output_field=models.IntegerField())).values('subcount')
    authors = Author.objects \
        .annotate(citation_count=SumSubquery(cite)) \
        .annotate(publication_count=SumSubquery(p_tot)) \
        .annotate(publication_avail_code_count=SumSubquery(p_avail)) \
        .filter(citation_count__isnull=False) \
        .values('id', 'given_name', 'family_name', 'orcid', 'researcherid', 'email',
                'citation_count', 'publication_count', 'publication_avail_code_count') \
        .distinct()

    publication_author_df = pd.DataFrame.from_records(publication_authors)
    author_df = pd.DataFrame.from_records(authors)
    author_df.publication_avail_code_count = author_df.publication_avail_code_count.fillna(0).astype('int')
    return publication_author_df, author_df


def get_code_archive_urls(publications):
    codearchiveurls = CodeArchiveUrl.objects \
        .filter(publication__in=publications) \
        .values('id', 'status', 'category__category', 'category__subcategory', 'url', 'publication_id')
    codearchiveurl_df = pd.DataFrame.from_records(codearchiveurls, index='id').rename(
        columns={'category__category': 'category', 'category__subcategory': 'subcategory'})

    return codearchiveurl_df


def get_model_documentation(publications):
    publication_modeldocumentation = PublicationModelDocumentations.objects \
        .filter(publication__in=publications) \
        .values('publication_id', 'model_documentation_id')
    publication_modeldocumentation_df = pd.DataFrame.from_records(publication_modeldocumentation)

    modeldocumentation = ModelDocumentation.objects \
        .filter(publications__in=publications) \
        .values('id', 'name') \
        .distinct()
    modeldocumentation_df = pd.DataFrame.from_records(modeldocumentation, index='id').rename(
        columns={'name': 'raw_name'})
    modeldocumentation_df['name'] = 'Documentation (' + modeldocumentation_df['raw_name'].map(str) + ')'
    return publication_modeldocumentation_df, modeldocumentation_df


def get_platforms(publications):
    publication_platforms = PublicationPlatforms.objects \
        .filter(publication__in=publications) \
        .values('publication_id', 'platform_id')
    publication_platform_df = pd.DataFrame.from_records(publication_platforms)

    platforms = Platform.objects \
        .annotate(count=Count('publications', Q(publications__is_primary=True) & Q(publications__status='REVIEWED'))) \
        .filter(count__gt=0).values('id', 'name', 'count')
    platform_df = pd.DataFrame.from_records(platforms, index='id').sort_values('count', ascending=False).rename(
        columns={'name': 'raw_name'})
    platform_df['name'] = "Platform (" + platform_df['raw_name'].map(str) + ")"
    platform_df['name'][50:] = 'Platform Other'

    return publication_platform_df, platform_df


def get_sponsors(publications):
    publication_sponsors = PublicationSponsors.objects \
        .filter(publication__in=publications) \
        .values('publication_id', 'sponsor_id')
    publication_sponsor_df = pd.DataFrame.from_records(publication_sponsors)

    sponsors = Sponsor.objects \
        .annotate(count=Count('publications', Q(publications__is_primary=True) & Q(publications__status='REVIEWED'))) \
        .filter(count__gt=0).values('id', 'name', 'count')
    sponsor_df = pd.DataFrame.from_records(sponsors, index='id').sort_values('count', ascending=False).rename(
        columns={'name': 'raw_name'})
    sponsor_df['name'] = sponsor_df['raw_name']
    sponsor_df['name'] = "Sponsor (" + sponsor_df['name'].map(str) + ")"
    sponsor_df['name'][50:] = 'Sponsor Other'

    return publication_sponsor_df, sponsor_df


def _create_publication_dummies(publication_related_df: pd.DataFrame, related_df: pd.DataFrame, index_name):
    df = publication_related_df.set_index(index_name).join(related_df)
    df = pd.get_dummies(df['name'], dtype=bool).set_index(df['publication_id']).groupby(
        'publication_id').any().astype(np.uint8)
    return df


def create_publication_modeldocumentation_dummies(publication_modeldocumentation_df, modeldocumentation_df):
    return _create_publication_dummies(publication_related_df=publication_modeldocumentation_df,
                                       related_df=modeldocumentation_df, index_name='model_documentation_id')


def create_publication_platform_dummies(publication_platform_df, platform_df):
    return _create_publication_dummies(publication_related_df=publication_platform_df,
                                       related_df=platform_df, index_name='platform_id')


def create_publication_sponsor_dummies(publication_sponsor_df, sponsor_df):
    return _create_publication_dummies(publication_related_df=publication_sponsor_df,
                                       related_df=sponsor_df, index_name='sponsor_id')


def determine_code_archival_status(row):
    has_urls = row['count'] > 0
    has_unavailable = row['count_unavailable'] > 0
    has_archive = row['count_archived'] > 0
    if has_unavailable or not has_urls:
        return 'NOT_AVAILABLE'
    elif not has_archive:
        return 'NOT_IN_ARCHIVE'
    else:
        return 'ARCHIVED'


def get_publications(publications, modeldocumentation_dummies, platform_dummies, sponsor_dummies, codearchiveurls):
    def get_publication_row(publication):
        attrs = [
            "id", "title", "abstract", "short_title", "contact_email", "email_sent_count",
            "contact_author_name", "is_primary", "doi",
            "series_text", "series_title", "series", "issue", "volume", "pages", "author_names",
            "year_published"
        ]
        d = {}
        for attr in attrs:
            d[attr] = getattr(publication, attr)

        d["container__issn"] = publication.container.issn
        d["container__name"] = publication.container.name
        return d

    df = pd.DataFrame.from_records(
        (get_publication_row(p) for p in publications.annotate(
            author_names=ArrayAgg(Concat(F('creators__given_name'), Value(' '), F('creators__family_name')),
                                  ordering=('creators__family_name', 'creators__given_name')))), index='id')
    codearchiveurls['count_archived'] = codearchiveurls.category == 'Archive'
    codearchiveurls['count_unavailable'] = codearchiveurls.status != 'available'
    codearchiveurls['count'] = 1
    codearchiveurls = codearchiveurls[['count_archived', 'count_unavailable', 'count', 'publication_id']] \
        .groupby('publication_id').sum().reindex(df.index, fill_value=0.0)
    codearchiveurls['code_archival_status'] = codearchiveurls.apply(determine_code_archival_status, axis=1)

    df = df \
        .join(codearchiveurls[['code_archival_status']]) \
        .join(modeldocumentation_dummies) \
        .join(platform_dummies) \
        .join(sponsor_dummies)
    criteria = (df.dtypes == np.float) & pd.Series(df.columns != 'year_published', df.columns)
    df.loc[:, criteria] = df.loc[:, criteria].fillna(0.0)
    return df


def export(path):
    remove_recoded = lambda df: df[['raw_name']].rename(columns={'raw_name': 'name'})

    path = pathlib.Path(path)
    publications = get_queryset()

    publication_author_df, author_df = get_authors(publications)
    publication_author_df.to_csv(path.joinpath('publication_author.csv'))
    author_df.to_csv(path.joinpath('author.csv'))

    codearchiveurl_df = get_code_archive_urls(publications)
    codearchiveurl_df.to_csv(path.joinpath('codearchiveurl.csv'))

    publication_modeldocumentation_df, modeldocumentation_df = get_model_documentation(publications)
    publication_modeldocumentation_df.to_csv(path.joinpath('publication_modeldocumentation.csv'))
    remove_recoded(modeldocumentation_df).to_csv(path.joinpath('modeldocumentation.csv'))
    modeldocumentation_dummies_df = create_publication_modeldocumentation_dummies(publication_modeldocumentation_df,
                                                                                  modeldocumentation_df)

    publication_platform_df, platform_df = get_platforms(publications)
    publication_platform_df.to_csv(path.joinpath('publication_platform.csv'))
    remove_recoded(platform_df).to_csv(path.joinpath('platform.csv'))
    platform_dummies_df = create_publication_platform_dummies(publication_platform_df, platform_df)

    publication_sponsor_df, sponsor_df = get_sponsors(publications)
    publication_sponsor_df.to_csv(path.joinpath('publication_sponsor.csv'))
    remove_recoded(sponsor_df).to_csv(path.joinpath('sponsor.csv'))
    sponsor_dummies_df = create_publication_sponsor_dummies(publication_sponsor_df, sponsor_df)

    publication_df = get_publications(publications,
                                      modeldocumentation_dummies=modeldocumentation_dummies_df,
                                      platform_dummies=platform_dummies_df,
                                      sponsor_dummies=sponsor_dummies_df,
                                      codearchiveurls=codearchiveurl_df)
    publication_df.to_csv(path.joinpath('publication.csv'))

    get_publication_network(publications).to_csv(path.joinpath('publication_network.csv'))
