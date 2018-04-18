from collections import Counter

from haystack.query import SearchQuerySet
from dateutil.parser import parse as datetime_parse
from datetime import datetime

from .globals import NetworkGroupBYType
from ..models import Publication, URLStatusLog
from ..ping_urls import categorize_url

from django.db.models import Max, Count

import logging

logger = logging.getLogger(__name__)


class NetworkData:
    graph = {}
    filter_value = {}

    def __init__(self, nodes, links, filter_value):
        self.graph = {'links': links, 'nodes': nodes}
        self.filter_value = filter_value


# Generates unique list of nodes that will be used in network based on the provided link list
def generate_node_candidates(links_candidates):
    nodes = set()
    for source, target in links_candidates:
        nodes.add(source)
        nodes.add(target)
    return nodes


# Generates links that will be used to form the network based on the provided filter criteria
def generate_link_candidates(filter_criteria):

    start_year = 1901
    end_year = 2100

    if 'date_published__gte' in filter_criteria:
        start_year = datetime.strptime(filter_criteria.pop('date_published__gte'), '%Y-%m-%dT%H:%M:%SZ').year
    if 'date_published__lte' in filter_criteria:
        end_year = datetime.strptime(filter_criteria.pop('date_published__lte'), '%Y-%m-%dT%H:%M:%SZ').year

    # fetching only filtered publication
    primary_publications = Publication.api.primary(**filter_criteria)

    primary_pk = []
    primary_pubs = []
    for pub in primary_publications:
        if pub.year_published is not None and start_year <= pub.year_published <= end_year:
            primary_pk.append(pub.pk)
            primary_pubs.append(pub)

    # fetches links that satisfies the given filter
    links_candidates = primary_publications.filter(pk__in=primary_pk, citations__in=primary_pubs).values_list('pk',
                                                                                                              'citations')
    return links_candidates


def get_network_default_filter(group_by):
    if group_by == NetworkGroupBYType.SPONSOR.value:
        # FIXME: this should be abstracted into a method like Publication.api.sponsors_with_count(number=10)
        sponsors = Publication.api.primary(status="REVIEWED").values('sponsors__name').order_by(
            'sponsors__name').annotate(count=Count('sponsors__name')).values(
                'count', 'sponsors__name').order_by('-count')[:10]
        return [sponsor['sponsors__name'] for sponsor in sponsors]
    else:
        # FIXME: this should be abstracted into a method in Publication.api, e.g.,
        # Publication.api.tags_with_count(number=10)
        tags = Publication.api.primary(status="REVIEWED").values('tags__name').order_by(
            'tags__name').annotate(count=Count('tags__name')).values(
                'count', 'tags__name').order_by('-count')[:10]
    return [tag['tags__name'] for tag in tags]


def generate_network_graph(filter_criteria, group_by=NetworkGroupBYType.TAGS.value):

    if group_by+'__name__in' in filter_criteria:
        filter_value = filter_criteria[group_by+'__name__in']
    else:
        filter_value = get_network_default_filter(group_by)
        filter_criteria[group_by+'__name__in'] = filter_value

    # fetches links that satisfies the given filter
    links_candidates = generate_link_candidates(filter_criteria)

    # discarding rest keeping only nodes used in forming network link
    nodes_candidates = generate_node_candidates(links_candidates)

    # Forming network group
    nodes, nodes_index = get_nodes(nodes_candidates, filter_value, group_by)
    links = get_links(links_candidates, nodes_index)

    filter_value.append("Others")
    return NetworkData(nodes, links, filter_value)


def get_links(links_candidates, nodes_index):
    links = []
    for source, target in links_candidates:
        links.append(
            {"source": nodes_index.index(source), "target": nodes_index.index(target),
             "value": 1})
    return links


def get_nodes(nodes_candidates, filter_value, group_by):
    # FIXME: the logic in this method is too complex / convoluted. simplify & refactor
    publication = Publication.api.primary(status="REVIEWED")
    nodes = []
    nodes_index = []
    for pub in nodes_candidates:
        if group_by == NetworkGroupBYType.SPONSOR.value:
            group_values = list(t[0] for t in publication.get(pk=pub).sponsors.all().values_list('name'))
        else:
            group_values = list(t[0] for t in publication.get(pk=pub).tags.all().values_list('name'))
        value = next((values for values in group_values if values in filter_value), None)
        group = "Others"
        if value:
            group = value

        nodes_index.append(pub)
# FIXME: this particular expression needs to be cleaned up & refactored
        nodes.append({"name": pub, "group": group, 'tags': ','.join(
            ['{0}'.format(s.name) for s in
             publication.get(pk=pub).tags.all()]), 'sponsors': ','.join(
            ['{0}'.format(s.name) for s in
             publication.get(pk=pub).sponsors.all()]), "Authors": ', '.join(
            ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
             publication.get(pk=pub).creators.all()]), "title": publication.filter(pk=pub).values_list('title')[0][0]})
    return nodes, nodes_index


def generate_aggregated_distribution_data(filter_criteria, classifier, name):
    sqs = SearchQuerySet()
    pubs = sqs.filter(**filter_criteria).models(Publication)
    availability = Counter()
    non_availability = Counter()
    years_list = []
    if pubs:
        for pub in pubs:
            is_archived = pub.is_archived
            try:
                date_published = int(datetime_parse(str(pub.date_published)).year)
            except:
                date_published = None
            if date_published is not None:
                years_list.append(date_published)
                bucket = availability if is_archived else non_availability
                bucket[date_published] += 1

        distribution_data = []
        count = len(years_list)
        for year in set(years_list):
            present = availability[year] * 100 / count
            absent = non_availability[year] * 100 / count
            total = present + absent
            distribution_data.append({
                'relation': classifier, 'name': name, 'date': year,
                'Code Available': availability[year],
                'Code Not Available': non_availability[year],
                'Code Available Per': present * 100 / total,
                'Code Not Available Per': absent * 100 / total
            })

        return distribution_data


def generate_aggregated_code_archived_platform_data(filter_criteria=None):
    if filter_criteria is None:
        filter_criteria = {}
    url_logs = URLStatusLog.objects.all().values('publication').order_by('publication', '-last_modified'). \
        annotate(last_modified=Max('last_modified')).values('publication', 'type').order_by('publication')

    platform_dct = {}

    if url_logs:
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: url_logs.filter(type=platform_name[0]).count()})
        return platform_dct
    else:
        sqs = SearchQuerySet()
        sqs = sqs.filter(**filter_criteria).models(Publication)
        filtered_pubs = queryset_gen(sqs)
        pubs = Publication.api.primary(pk__in=filtered_pubs)
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: 0})
        for pub in pubs:
            if pub.code_archive_url is not '':
                platform_type = categorize_url(pub.code_archive_url)
                platform_dct.update({platform_type: platform_dct[platform_type] + 1})
        return platform_dct


def queryset_gen(search_qs):
    for item in search_qs:
        yield item.pk
