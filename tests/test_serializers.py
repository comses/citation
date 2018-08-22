import time

from collections import OrderedDict
from unittest.mock import patch

from rest_framework import serializers

from citation.models import AuditCommand, AuditLog, Container, Publication, PublicationPlatforms, Platform, \
    Author, \
    PublicationAuthors
from citation.serializers import PublicationSerializer, ContactFormSerializer
from citation.util import create_timestamp_hash

from .common import BaseTest


class PublicationSerializerTest(BaseTest):
    def setUp(self):
        self.user = self.create_user(username='bobsmith',
                                     email='a@b.com', password='test')
        self.author = Author.objects.create(given_name='Bob', family_name='Smith', type=Author.INDIVIDUAL)
        self.container = Container.objects.create(name='JASSS')
        self.platform = Platform.objects.create(name='JVM')
        self.publication = Publication.objects.create(
            title='Foo', added_by=self.user, container=self.container)
        self.publication_platform = PublicationPlatforms.objects.create(
            platform=self.platform, publication=self.publication)
        self.publication_author = PublicationAuthors.objects.create(
            author=self.author, publication=self.publication, role=PublicationAuthors.RoleChoices.AUTHOR)

    def test_add_platform_to_publication(self):
        initial_auditlog_count = AuditLog.objects.count()
        initial_audit_command_count = AuditCommand.objects.count()
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        if serializer.is_valid():
            serializer.save(self.user)
        # If no changes were made to the data nothing should be logged in the auditlog
        self.assertEqual(AuditLog.objects.count(), initial_auditlog_count)
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 1)

        platform_cpp = Platform.objects.create(name='C++')
        PublicationPlatforms.objects.create(platform=platform_cpp, publication=self.publication)
        serializer = PublicationSerializer(Publication.objects.first())
        serializer = PublicationSerializer(Publication.objects.first(), data=serializer.data)
        if serializer.is_valid():
            serializer.save(self.user)
        self.assertEqual(AuditLog.objects.filter(table='publicationplatforms').count(), 0)
        self.assertEqual(AuditLog.objects.filter(table='platform').count(), 0)
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 2)

        platform_pascal_str = 'Pascal'
        serializer = PublicationSerializer(Publication.objects.first())
        data = serializer.data
        data['platforms'] = [OrderedDict(name=platform_pascal_str, url='', description='')]
        serializer = PublicationSerializer(Publication.objects.first(), data=data)
        if serializer.is_valid():
            serializer.save(self.user)
        # Two Deletes and One Insert
        self.assertEqual(AuditLog.objects.filter(table='publicationplatforms').count(), 3)
        self.assertEqual(AuditLog.objects.filter(table='platform').count(), 1)
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 3)


class ContactFormSerializerTestCase(BaseTest):
    def test_honey_pot(self):
        serializer = ContactFormSerializer(instance={})
        self.assertFalse(serializer.validate_contact_number(''))
        with self.assertRaises(serializers.ValidationError):
            serializer.validate_contact_number('foo')

    @patch('citation.serializers.time.time', return_value=10)
    def test_timestamp(self, mock_time):
        serializer = ContactFormSerializer(instance={})
        serializer.validate_timestamp(mock_time.return_value - 4)
        with self.assertRaises(serializers.ValidationError):
            serializer.validate_timestamp(mock_time.return_value - 1)

    def test_security_hash_timestamp_cannot_be_altered(self):
        serializer = ContactFormSerializer(instance={})
        t = time.time()
        security_hash = create_timestamp_hash(t)
        serializer.validate(dict(security_hash=security_hash, timestamp=t))
        with self.assertRaises(serializers.ValidationError):
            serializer.validate(dict(security_hash=security_hash, timestamp=t+1))