from ..models import Publication,  URLStatusLog
from ..ping_urls import categorize_url


from django.db.models import Max

import logging

logger = logging.getLogger(__name__)

SPONSORS_DEFAULT_FILTERS = ["United States National Science Foundation (NSF)"]
TAGS_DEFAULT_FILTERS = ["Dynamics", "Simulation"]

class NetworkData:
    graph = {}
    filter_value = {}

    def __init__(self, nodes, links, filter_value):
        self.graph = {'links': links, 'nodes': nodes}
        self.filter_value = filter_value

class AggregatedData:
    data = []
    code_archived_platform = []

    def __init__(self, data, platform_name):
        self.data = data
        self.code_archived_platform = [platform_name]

def generate_network_graph_group_by_sponsors(filter_criteria):
    publication = Publication.api.primary(status="REVIEWED").prefetch_related('sponsors', 'creators')
    nodes = []
    links = []
    tmp = []
    if 'sponsors__name__in' in filter_criteria:
        sponsors_filter = filter_criteria['sponsors__name__in']
    else :
        sponsors_filter = SPONSORS_DEFAULT_FILTERS
        filter_criteria['sponsors__name__in'] = sponsors_filter
    # fetching only filtered publication
    primary_publications = Publication.api.primary(status='REVIEWED', **filter_criteria)

    # fetches links that satisfies the given filter
    links_candidates = Publication.api.primary(status='REVIEWED', **filter_criteria,
                                               citations__in=primary_publications).values_list('pk', 'citations')

    # discarding rest keeping only nodes used in forming network link
    nodes_candidates = generate_node_candidates(links_candidates)

    # generates set of nodes for graph data and identify which group node belongs to
    # by mapping publication tags values with the user requested tags value
    # Appending additional info to the node(publication) i.e authors, title, tags
    for pub in nodes_candidates:
        sponsors = list(t[0] for t in publication.get(pk=pub).sponsors.all().values_list('name'))
        value = next((sponsor for sponsor in sponsors if sponsor in sponsors_filter), None)
        if value:
            tmp.append(pub)
            nodes.append({"name": pub, "group": value, 'tags': ','.join(
                ['{0}'.format(t.name) for t in
                 publication.get(pk=pub).tags.all()]), 'sponsors': sponsors, "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})
        else:
            tmp.append(pub)
            nodes.append({"name": pub, "group": "others", 'tags': ','.join(
                ['{0}'.format(t.name) for t in
                 publication.get(pk=pub).tags.all()]), 'sponsors': sponsors, "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})

    # Identifies link between two nodes and caching all connected node for generating collapsible tree structure
    for pub in links_candidates:
        links.append({"source": tmp.index(pub[0]), "target": tmp.index(pub[1]), "value": 1})

    sponsors_filter.append("others")
    return NetworkData(nodes, links, sponsors_filter)


def generate_network_graph_group_by_tags(filter_criteria):
    publication = Publication.api.primary(status="REVIEWED").prefetch_related('tags', 'creators')
    nodes = []
    links = []
    tmp = []
    if 'tags__name__in' in filter_criteria:
        tags_filter = filter_criteria['tags__name__in']
    else:
        tags_filter = TAGS_DEFAULT_FILTERS
        filter_criteria['tags__name__in'] = tags_filter
    # fetching only filtered publication
    primary_publications = Publication.api.primary(status='REVIEWED', **filter_criteria)

    # fetches links that satisfies the given filter
    links_candidates = Publication.api.primary(status='REVIEWED', **filter_criteria,
                                               citations__in=primary_publications).values_list('pk', 'citations')

    # discarding rest keeping only nodes used in forming network link
    nodes_candidates = generate_node_candidates(links_candidates)
    # Forming network group by tags
    for pub in nodes_candidates:
        tags = list(t[0] for t in publication.get(pk=pub).tags.all().values_list('name'))
        value = next((tag for tag in tags if tag in tags_filter), None)
        if value:
            tmp.append(pub)
            nodes.append({"name": pub, "group": value, 'tags': tags, 'sponsors': ','.join(
                ['{0}'.format(s.name) for s in
                 publication.get(pk=pub).sponsors.all()]), "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})
        else:
            tmp.append(pub)
            nodes.append({"name": pub, "group": "others", 'tags': tags, 'sponsors': ','.join(
                ['{0}'.format(s.name) for s in
                 publication.get(pk=pub).sponsors.all()]), "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})
    for pub in links_candidates:
        links.append(
            {"source": tmp.index(pub[0]), "target": tmp.index(pub[1]),
             "value": 1})
    tags_filter.append("others")
    return NetworkData(nodes, links, tags_filter)


def generate_node_candidates(links_candidates):
    nodes = set()
    for pub in links_candidates:
        nodes.add(pub[1])
        nodes.add(pub[0])
    return nodes


def generate_publication_code_platform_data(filter_criteria, classifier, name):
    pubs = Publication.api.primary(status='REVIEWED', **filter_criteria)
    url_logs = URLStatusLog.objects.filter(publication__in=pubs).values('publication').order_by('publication', '-last_modified'). \
        annotate(last_modified=Max('last_modified')).values('publication', 'type').order_by('publication')

    platform_dct = {}
    availability = []
    non_availability = []
    years_list = []

    if url_logs:
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: url_logs.filter(type=platform_name[0]).count()})
    else:
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: 0})
        for pub in pubs:
            if pub.code_archive_url is not '':
                platform_type = categorize_url(pub.code_archive_url)
                platform_dct.update({platform_type: platform_dct[platform_type] + 1})

    if pubs:
        for pub in pubs:
            if pub.year_published is not None and pub.code_archive_url is not '':
                availability.append(pub.year_published)
            else:
                non_availability.append(pub.year_published)
            years_list.append(pub.year_published)

        distribution_data = []
        for year in set(years_list):
            if year is not None:
                present = availability.count(year) * 100 / len(years_list)
                absent = non_availability.count(year) * 100 / len(years_list)
                total = present + absent
                distribution_data.append(
                    {'relation': classifier, 'name': name, 'date': year,
                     'Code Available': availability.count(year),
                     'Code Not Available': non_availability.count(year),
                     'Code Available Per': present * 100 / total,
                     'Code Not Available Per': absent * 100 / total})

        return AggregatedData(distribution_data, platform_dct)
