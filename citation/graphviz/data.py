from collections import Counter
from dateutil.parser import parse as datetime_parse

from .globals import NetworkGroupByType, RelationClassifier
from ..models import Publication, URLStatusLog
from ..ping_urls import categorize_url

from django.db.models import Max

import logging

logger = logging.getLogger(__name__)

VIZ_DEFAULT_FILTER = {'status': 'REVIEWED', 'is_primary': True}


class VisualizationData:

    def __init__(self, data, group):
        self.data = data
        self.group = group


class VisualizationBaseClass:

    def __init__(self, filter_criteria=None):
        self.start_year = 1901
        self.end_year = 2100
        self.filter_criteria = filter_criteria

        if self.filter_criteria is None:
            self.filter_criteria = VIZ_DEFAULT_FILTER

        if 'start_year' in self.filter_criteria:
            self.start_year = self.filter_criteria.pop('start_year')
        if 'end_year' in self.filter_criteria:
            self.end_year = self.filter_criteria.pop('end_year')

        # fetching only filtered publication
        self.publications = Publication.api.primary(**self.filter_criteria)

    def qualify(self, year_published):
        if year_published and self.start_year <= year_published <= self.end_year:
            return year_published

        return None


class NetworkVisualization(VisualizationBaseClass):

    def __init__(self, filter_criteria=None, group_by=NetworkGroupByType.TAGS.value):
        super().__init__(filter_criteria)

        self.group_by = group_by
        if group_by + '__name__in' in self.filter_criteria:
            self.filter_value = self.filter_criteria[group_by + '__name__in']
        else:
            self.filter_value = self.get_default_group_by_filter()
            self.filter_criteria[group_by + '__name__in'] = self.filter_value

    def get_default_group_by_filter(self):
        if self.group_by == NetworkGroupByType.SPONSOR.value:
            return Publication.api.get_top_records('sponsors__name', 5)
        else:
            return Publication.api.get_top_records('tags__name', 5)

    def get_common_value(self, first, second):
        """
        :param first: list
        :param second: list
        :return: first common value found
        """
        for value in first:
            if value in second:
                return value

        return None

    # Generates links that will be used to form the network based on the provided filter criteria
    def generate_link_candidates(self):
        primary_pk = []
        primary_pubs = []
        for pub in self.publications:
            if self.qualify(pub.year_published):
                primary_pk.append(pub.pk)
                primary_pubs.append(pub)

        # fetches links that satisfies the given filter
        links_candidates = self.publications.filter(pk__in=primary_pk, citations__in=primary_pubs).values_list('pk',
                                                                                                               'citations')
        return links_candidates

    # Generates unique list of nodes that will be used in network based on the provided link list
    def generate_node_candidates(self, links_candidates):
        nodes = set()
        for source, target in links_candidates:
            nodes.add(source)
            nodes.add(target)

        return list(nodes)

    def get_nodes(self, nodes_candidates):
        publications = Publication.api.primary(status="REVIEWED")
        nodes = []
        for pub in nodes_candidates:
            publication = publications.get(pk=pub)
            group_values = []
            if self.group_by == NetworkGroupByType.SPONSOR.value:
                for name in publication.sponsors.all().values_list('name', flat=True):
                    group_values.append(name)
            else:
                for name in publication.tags.all().values_list('name', flat=True):
                    group_values.append(name)

            value = self.get_common_value(group_values, self.filter_value)
            if value:
                group = value
            else:
                group = "Others"

            nodes.append({
                'name': pub,
                'group': group,
                'tags': ', '.join(['{0}'.format(s.name) for s in publication.tags.all()]),
                'sponsors': ', '.join(['{0}'.format(s.name) for s in publication.sponsors.all()]),
                'Authors': ', '.join(
                    ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in publication.creators.all()]),
                'title': publication.title
            })

        return nodes

    def get_links(self, links_candidates, nodes_index):
        links = []
        for source, target in links_candidates:
            links.append({
                "source": nodes_index.index(source), "target": nodes_index.index(target), "value": 1
            })

        return links

    def get_data(self):
        # fetches links that satisfies the filter criteria
        links_candidates = self.generate_link_candidates()

        # discarding rest keeping only nodes used in forming network link
        nodes_candidates = self.generate_node_candidates(links_candidates)

        # Forming network group
        nodes = self.get_nodes(nodes_candidates)
        links = self.get_links(links_candidates, nodes_candidates)
        data = {'nodes': nodes, 'links': links}

        return VisualizationData(data, self.filter_value)


class AggregatedDistributionVisualization(VisualizationBaseClass):

    def __init__(self, filter_criteria=None):
        super().__init__(filter_criteria)

    def get_distribution_data(self, visualization_category, header_name):
        availability = Counter()
        non_availability = Counter()
        years_list = []
        for pub in self.publications:
            year_published = self.qualify(pub.year_published)
            if year_published:
                years_list.append(year_published)
                bucket = availability if pub.is_archived else non_availability
                bucket[year_published] += 1

        distribution_data = []
        year_count = len(years_list)
        for year in set(years_list):
            present = availability[year] * 100 / year_count
            absent = non_availability[year] * 100 / year_count
            total = present + absent
            distribution_data.append({
                'relation': visualization_category, 'name': header_name, 'date': year,
                'Code Available': availability[year],
                'Code Not Available': non_availability[year],
                'Code Available Per': present * 100 / total,
                'Code Not Available Per': absent * 100 / total
            })

        return distribution_data

    def get_aggregated_archived_platform(self):
        platform_dct = {}
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: 0})
        for pub in self.publications:
            if pub.is_archived:
                platform_type = categorize_url(pub.code_archive_url)
                platform_dct.update({platform_type: platform_dct[platform_type] + 1})

        return [platform_dct]

    def get_data(self, visualization_category=RelationClassifier.GENERAL.value, header_name='Publications'):
        data = self.get_distribution_data(visualization_category, header_name)
        platform = self.get_aggregated_archived_platform()

        return VisualizationData(data, platform)


class AggregatedCodeArchivedLocationVisualization(VisualizationBaseClass):
    def __init__(self, filter_criteria=None):
        super().__init__(filter_criteria)

        self.url_status_logs = URLStatusLog.objects.all().values('publication'). \
            order_by('publication', '-last_modified'). \
            annotate(last_modified=Max('last_modified')). \
            values_list('publication', 'type', 'publication__date_published_text').order_by('publication')

    def get_data(self):
        all_records = Counter()
        years_list = []
        if self.url_status_logs:
            for pub, category, date_published in self.url_status_logs:
                try:
                    year_published = int(datetime_parse(date_published).year)
                except ValueError:
                    year_published = None
                year_published = self.qualify(year_published)
                if year_published:
                    years_list.append(year_published)
                    all_records[(year_published, category)] += 1
        else:
            for pub in self.publications:
                year_published = self.qualify(pub.year_published)
                if pub.is_archived and year_published:
                    years_list.append(year_published)
                    all_records[(year_published, categorize_url(pub.code_archive_url))] += 1

        group = []
        data = [['x']]
        for name in URLStatusLog.PLATFORM_TYPES:
            group.append(name[0])
            data.append([name[0]])

        for year in sorted(set(years_list)):
            data[0].append(year)
            index = 1
            for name in URLStatusLog.PLATFORM_TYPES:
                data[index].append(all_records[(year, name[0])])
                index += 1

        return VisualizationData(data, group)

