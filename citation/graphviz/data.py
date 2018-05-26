from collections import Counter

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

        self.filter_criteria = filter_criteria

        if self.filter_criteria is None:
            self.filter_criteria = VIZ_DEFAULT_FILTER

        # fetching only filtered publication
        self.publications = Publication.api.primary(**self.filter_criteria)


class NetworkVisualization(VisualizationBaseClass):

    def __init__(self, filter_criteria=None, group_by=NetworkGroupByType.TAGS):
        super().__init__(filter_criteria)

        self.group_by = group_by
        if self.group_by.filter_syntax() in self.filter_criteria:
            self.filter_value = self.filter_criteria[self.group_by.filter_syntax()]
        else:
            self.filter_value = Publication.api.get_top_records(self.group_by.top_record_attr(), 5)
            self.filter_criteria[group_by.filter_syntax()] = self.filter_value

        self.publications = Publication.api.primary(**self.filter_criteria)

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

    # Generates unique list of nodes that will be used in network based on the provided link list
    def generate_node_candidates(self, links_candidates):
        nodes = set()
        for source, target in links_candidates:
            nodes.add(source)
            nodes.add(target)

        return list(nodes)

    def get_nodes(self, nodes_candidates):
        nodes = []
        for pub in nodes_candidates:
            publication = Publication.api.primary(pk=pub)
            tags = publication.values_list('tags__name', flat=True)
            sponsors = publication.values_list('sponsors__name', flat=True)
            creator = publication.values_list('creators__family_name', 'creators__given_name')
            if self.group_by.is_sponsor():
                group_values = sponsors
            else:
                group_values = tags

            value = self.get_common_value(group_values, self.filter_value)
            if value:
                group = value
            else:
                group = "Others"

            nodes.append({
                'name': pub,
                'group': group,
                'tags': ', '.join(['{0}'.format(tag) for tag in tags]),
                'sponsors': ', '.join(['{0}'.format(sponsor) for sponsor in sponsors]),
                'Authors': ', '.join(
                    ['{0}, {1}.'.format(c[0], c[1]) for c in creator]),
                'title': publication.values_list('title', flat=True)[0]
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
        # Generates links that will be used to form the network based on the provided filter criteria
        # e.g: l_c = [(100,400),(100,300),(300,200)]
        links_candidates = self.publications.filter(pk__in=self.publications,
                                                    citations__in=self.publications).values_list('pk','citations')

        # discarding rest keeping only nodes used in forming network link
        # e.g: n_c = [100,200,300,400]
        nodes_candidates = self.generate_node_candidates(links_candidates)

        # Forming network group
        nodes = self.get_nodes(nodes_candidates)
        # e.g: links  = [{ 'source':0 , 'target':3}, {'source': 0, 'target':2}, {'source': 2, 'target':1}]
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
            year_published = pub.date_published.year
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
            values_list('publication', 'type', 'publication__date_published').order_by('publication')

    def get_data(self):
        all_records = Counter()
        years_list = []
        if self.url_status_logs:
            for pub, category, date_published in self.url_status_logs:
                year_published = date_published.year
                if year_published:
                    years_list.append(year_published)
                    all_records[(year_published, category)] += 1
        else:
            for pub in self.publications:
                year_published = pub.date_published.year
                archive_url = pub.code_archive_url
                if archive_url is not '' and year_published:
                    years_list.append(year_published)
                    all_records[(year_published, categorize_url(archive_url))] += 1


        # converting to d3 format(staged-bar):
        # [
        #  [x, 2000, 2001, 2002, 2003]
        #  ['COMSES', 0, 0, 0, 0],
        #  ['OPEN SOURCE', 0, 0, 0, 1],
        #  ['PLATFORM', 0, 0, 0, 0],
        #  ['JOURNAL', 0, 0, 0, 0],
        #  ['PERSONAL', 0, 0, 0, 1],
        #  ['INVALID', 0, 0, 0, 0],
        #  ['OTHERS', 1, 2, 1, 0]
        # ]
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

