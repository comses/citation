from django.db.models import Max
from django.db.models import Q
from django.test import TestCase
from autofixture import AutoFixture
from django.contrib.auth.models import User

from citation import models


class TestModelManagers(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestModelManagers, cls).setUpClass()
        cls.user = User.objects.create_user(username="foo", email="a@b.com", password="bar")
        cls.second_user = User.objects.create_user(username="bar", email="bar@b.com", password="bar")
        cls.author_detached = {'orcid': '1234', 'type': 'foo', 'given_name': 'Bob', 'family_name': 'Smith'}
        cls.context = models.AuditCommand.objects.create(
            creator=cls.user, action=models.AuditCommand.Action.MANUAL)
        cls.second_context = models.AuditCommand.objects.create(
            creator=cls.second_user, action=models.AuditCommand.Action.MANUAL)
        cls.publication = AutoFixture(models.Publication, generate_fk=['container']).create(1)

    @staticmethod
    def to_dict(instance):
        return {field.column: getattr(instance, field.column) for field in instance._meta.local_fields}

    def check_auditlog(self, user, action, instance, auditlog):
        payload = TestModelManagers.to_dict(instance)
        table = instance._meta.db_table
        self.assertEqual(auditlog.user_id, user.id)
        self.assertEqual(auditlog.table, table)
        self.assertEqual(auditlog.action, action)
        self.assertEqual(auditlog.payload, payload)

    def test_author_log_create(self):
        author = models.Author.objects.log_create(audit_command=self.context, **self.author_detached)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'INSERT')
        self.assertEqual(auditlog.row_id, author.id)

    def test_author_log_get_or_create(self):
        author, created = models.Author.objects.log_get_or_create(
            audit_command=self.context, **self.author_detached)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'INSERT')
        self.assertEqual(auditlog.row_id, author.id)

        author2, created = models.Author.objects.log_get_or_create(
            audit_command=self.context, id=author.id, **self.author_detached)
        auditlog2 = models.AuditLog.objects.filter(action='UPDATE').first()
        self.assertEqual(auditlog2, None)

    def test_author_log_update(self):
        models.Author.objects.create(**self.author_detached)
        models.Author.objects.log_update(audit_command=self.context, given_name='Ralph')
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'UPDATE')
        self.assertEqual(auditlog.payload['data']['given_name']['new'], 'Ralph')
        self.assertEqual(auditlog.payload['data']['given_name']['old'], 'Bob')

    def test_author_log_delete(self):
        author = models.Author.objects.create(**self.author_detached)
        author_contents = {'id': author.id, 'orcid': author.orcid, 'type': author.type}
        models.Author.objects.all().log_delete(audit_command=self.context)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'DELETE')
        # auditlog.payload.pop('name')
        self.assertEqual(auditlog.payload['data']['given_name'], self.author_detached['given_name'])

    def test_audit_log_contribution(self):
        models.AuditLog.objects.create(row_id='1', table='publication', audit_command=self.context)
        models.AuditLog.objects.create(row_id='1', table='publication', audit_command=self.second_context)

        p = models.Publication.objects.get(pk=1)
        cd = p.contributor_data()

        date_values = models.AuditLog.objects.filter(Q(row_id='1') & Q(audit_command__action='MANUAL')).annotate(
            date_added=(Max('audit_command__date_added'))).values_list('date_added')

        # verify the contribution value
        date_value = date_values.filter(audit_command__creator__username='bar')
        self.assertDictEqual(cd[0], {'creator': 'bar', 'contribution': 50, 'date_added': date_value[0][0]})

        date_value = date_values.filter(audit_command__creator__username='foo')
        self.assertDictEqual(cd[1], {'creator': 'foo', 'contribution': 50, 'date_added': date_value[0][0]})

        models.AuditLog.objects.create(row_id='1', table='publication', audit_command=self.second_context)

        p = models.Publication.objects.get(pk=1)
        cd = p.contributor_data()

        # verify the last date_added record is at top
        date_value = date_values.filter(audit_command__creator__username='bar')
        self.assertDictEqual(cd[0], {'creator': 'bar', 'contribution': 66, 'date_added': date_value[0][0]})
