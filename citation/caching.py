import itertools
import logging

from citation.models import Publication
from django.core.cache import cache
from django.db import connection
from django.db.models import Count

from catalog.core.views import generate_network_graph_group_by_tags, generate_network_graph_group_by_sponsors, \
                               generate_publication_code_platform_data

from catalog.core.util import RelationClassifier

logger = logging.getLogger(__name__)


def initialize_contributor_cache():
    with connection.cursor() as cursor:
        # NOTE : need to change to Django ORM
        cursor.execute(
            "select p.id, u.username, COUNT(u.username) as contribution, MAX(c.date_added) as date_added from "
            "citation_publication as p inner join citation_auditlog as a on a.pub_id_id = p.id or "
            "(a.row_id = p.id and a.table='publication') inner join citation_auditcommand as c on "
            "c.id = a.audit_command_id and c.action = 'MANUAL' inner join auth_user as u on c.creator_id=u.id "
            "where p.is_primary=True group by p.id,u.username, p.title order by p.id ")
        contributor_logs = _dictfetchall(cursor)

        cursor.execute(
            "select p.id, COUNT(p.id) as count from citation_publication as p inner join citation_auditlog as a "
            "on a.pub_id_id = p.id or (a.row_id = p.id and a.table='publication') inner join citation_auditcommand as c "
            "on c.id = a.audit_command_id and c.action = 'MANUAL' inner join auth_user as u on c.creator_id=u.id "
            "where p.is_primary=True  group by p.id order by p.id ")
        contributor_count = _dictfetchall(cursor)

        # Calculates the contribution percentages and combine the above two different table values into one
        combine = []
        for log in contributor_logs:
            temp = {}
            for count in contributor_count:
                if count['id'] == log['id']:
                    temp.update({'id': log['id'], 'contribution': "{0:.2f}".format(log['contribution'] * 100 / count['count']),
                                'creator': log['username'], 'date_added': log['date_added']})
                    combine.append(temp)

    # Creating a dict for publication having more than one contributor
    for k, v in itertools.groupby(combine, key=lambda x: x['id']):
        ls = []
        for dct in v:
            tmp = {}
            tmp.update(dct)
            ls.append(tmp)
        cache.set(dct['id'], ls, 86410)
    logger.debug("Contribution data cache completed.")

def _dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]

""" 
    Method to cache the default distribution of publication across the year 
    along with on which platform the code is made available information
"""
def initialize_publication_code_platform_cache():
    logger.debug("Caching publication distribution data")
    data, platform = generate_publication_code_platform_data({}, RelationClassifier.GENERAL, "Publications")
    cache.set("distribution_data", data, 86410)
    cache.set("platform_dct", platform, 86410)
    logger.debug("Publication code platform distribution data cache completed.")

"""
    Method to cache information about how the publication are connected
"""
def initialize_network_cache():
    logger.debug("Caching Network")

    #FIXME use more informational static filters over here
    sponsors_filter = list()
    sponsors = Publication.api.primary(status="REVIEWED").values('sponsors__name').order_by('sponsors__name'). \
               annotate(count=Count('sponsors__name')).values('count', 'sponsors__name').order_by('-count')[:10]
    for sponsor in sponsors:
        sponsors_filter.append(sponsor['sponsors__name'])
    filter_criteria = {'sponsors__name__in' : sponsors_filter}
    network, filter_list = generate_network_graph_group_by_sponsors(filter_criteria)
    cache.set("network-graph-sponsors", network, 86410)
    cache.set("network-graph-sponsors-filter", filter_list, 86410)
    logger.debug("Network cache for group_by sponsors completed using static filter: " + str(sponsors_filter))

    tags_filter = list()
    tags = Publication.api.primary(status= "REVIEWED").values('tags__name').order_by('tags__name').\
        annotate(count=Count('tags__name')).values('count','tags__name').order_by('-count')[:10]
    for tag in tags:
        tags_filter.append(tag['tags__name'])
    filter_criteria = {'tags__name__in': tags_filter}
    network, filter_list = generate_network_graph_group_by_tags(filter_criteria)
    cache.set("network-graph-tags", network, 86410)
    cache.set("network-graph-tags-filter", filter_list, 86410)
    logger.debug("Network cache for group_by tags completed using static filter: " + str(tags_filter))

