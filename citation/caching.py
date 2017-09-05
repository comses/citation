import itertools
import logging

from django.core import cache
from django.db import connection

logger = logging.getLogger(__name__)


def initialize_contributor_cache(self):
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
                    temp.update({'id': log['id'], 'contribution': log['contribution'] * 100 / count['count'],
                                'creator': log['username'], 'date_added': log['date_added']})
                    combine.append(temp)

    # Creating a dict for publication having more than one contributor
    for k, v in itertools.groupby(combine, key=lambda x: x['id']):
        ls = []
        for dct in v:
            tmp = {}
            tmp.update(dct)
            ls.append(tmp)
        cache.set(dct['id'], ls, 60 * 5)
    logger.debug("Caching completed.")


def _dictfetchall(self, cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]
