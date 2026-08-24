import time

from collections import OrderedDict
from unittest.mock import patch

from rest_framework import serializers

from citation.models import (
    AuditCommand,
    AuditLog,
    Container,
    Publication,
    PublicationPlatforms,
    Platform,
    Author,
    PublicationAuthors,
    CodeArchiveUrl,
    CodeArchiveUrlCategory,
)
from citation.serializers import (
    PublicationSerializer,
    ContactFormSerializer,
    SuggestMergeSerializer,
)
from citation.util import create_timestamp_hash

from .common import BaseTest


class PublicationSerializerTest(BaseTest):
    def setUp(self):
        self.user = self.create_user(
            username="bobsmith", email="a@b.com", password="test"
        )
        self.author = Author.objects.create(
            given_name="Bob", family_name="Smith", type=Author.INDIVIDUAL
        )
        self.container = Container.objects.create(name="JASSS")
        self.platform = Platform.objects.create(name="JVM")
        self.publication = Publication.objects.create(
            title="Foo", added_by=self.user, container=self.container
        )
        self.publication_platform = PublicationPlatforms.objects.create(
            platform=self.platform, publication=self.publication
        )
        self.publication_author = PublicationAuthors.objects.create(
            author=self.author,
            publication=self.publication,
            role=PublicationAuthors.RoleChoices.AUTHOR,
        )

    def test_add_platform_to_publication(self):
        initial_auditlog_count = AuditLog.objects.count()
        initial_audit_command_count = AuditCommand.objects.count()
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(self.user)
        # If no changes were made to the data nothing should be logged in the auditlog
        self.assertEqual(AuditLog.objects.count(), initial_auditlog_count)
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 1)

        platform_cpp = Platform.objects.create(name="C++")
        PublicationPlatforms.objects.create(
            platform=platform_cpp, publication=self.publication
        )
        serializer = PublicationSerializer(Publication.objects.first())
        serializer = PublicationSerializer(
            Publication.objects.first(), data=serializer.data
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(self.user)
        self.assertEqual(
            AuditLog.objects.filter(table="publicationplatforms").count(), 0
        )
        self.assertEqual(AuditLog.objects.filter(table="platform").count(), 0)
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 2)

        platform_pascal_str = "Pascal"
        serializer = PublicationSerializer(Publication.objects.first())
        data = serializer.data
        data["platforms"] = [
            OrderedDict(name=platform_pascal_str, url="", description="")
        ]
        serializer = PublicationSerializer(Publication.objects.first(), data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(self.user)
        # Two Deletes and One Insert
        self.assertEqual(
            AuditLog.objects.filter(table="publicationplatforms").count(), 3
        )
        self.assertEqual(AuditLog.objects.filter(table="platform").count(), 1)
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 3)

    def test_save_requires_user(self):
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with self.assertRaises(TypeError):
            serializer.save()

    def test_save_accepts_user_keyword(self):
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save(user=self.user)
        self.assertEqual(instance.id, self.publication.id)

    def test_save_rejects_commit_kwarg(self):
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with self.assertRaises(TypeError):
            serializer.save(user=self.user, commit=False)

    def test_save_concrete_changes_no_op(self):
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        initial_auditlog_count = AuditLog.objects.count()

        serializer.save(user=self.user)

        self.assertEqual(AuditLog.objects.count(), initial_auditlog_count)

    def test_save_concrete_changes_selective_field_update(self):
        serializer = PublicationSerializer(self.publication)
        data = serializer.data
        data["title"] = "Updated title"
        serializer = PublicationSerializer(self.publication, data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        serializer.save(user=self.user)

        self.publication.refresh_from_db()
        self.assertEqual(self.publication.title, "Updated title")
        auditlog = AuditLog.objects.filter(table="publication", action="UPDATE").get()
        self.assertEqual(auditlog.payload["data"]["title"]["new"], "Updated title")


class PublicationSerializerCodeArchiveTests(PublicationSerializerTest):
    def setUp(self):
        super().setUp()
        self.category = CodeArchiveUrlCategory.objects.create(
            category="Archive", subcategory="Repository"
        )

    def publication_data(self):
        serializer = PublicationSerializer(self.publication)
        return serializer.data

    def archive_url_data(self, url, status=CodeArchiveUrl.STATUS.available):
        return {
            "id": None,
            "category": self.category.id,
            "system_overridable_category": True,
            "url": url,
            "status": status,
            "creator": self.user.id,
        }

    def test_save_code_archive_urls_create(self):
        data = self.publication_data()
        data["code_archive_urls"] = [self.archive_url_data("https://example.com/code")]
        serializer = PublicationSerializer(self.publication, data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        serializer.save(user=self.user)

        archive_url = CodeArchiveUrl.objects.get(publication=self.publication)
        self.assertEqual(archive_url.creator, self.user)
        self.assertEqual(archive_url.url, "https://example.com/code")
        self.assertTrue(
            AuditLog.objects.filter(
                table="codearchiveurl", action="INSERT", row_id=archive_url.id
            ).exists()
        )

    def test_save_code_archive_urls_update(self):
        archive_url = CodeArchiveUrl.objects.create(
            creator=self.user,
            publication=self.publication,
            category=self.category,
            system_overridable_category=True,
            url="https://example.com/old",
            status=CodeArchiveUrl.STATUS.available,
        )
        data = self.publication_data()
        data["code_archive_urls"] = [
            {
                **self.archive_url_data(
                    "https://example.com/new", CodeArchiveUrl.STATUS.restricted
                ),
                "id": archive_url.id,
            }
        ]
        serializer = PublicationSerializer(self.publication, data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        serializer.save(user=self.user)

        archive_url.refresh_from_db()
        self.assertEqual(
            CodeArchiveUrl.objects.filter(publication=self.publication).count(), 1
        )
        self.assertEqual(archive_url.url, "https://example.com/new")
        self.assertEqual(archive_url.status, CodeArchiveUrl.STATUS.restricted)
        self.assertTrue(
            AuditLog.objects.filter(
                table="codearchiveurl", action="UPDATE", row_id=archive_url.id
            ).exists()
        )

    def test_save_code_archive_urls_delete(self):
        archive_url = CodeArchiveUrl.objects.create(
            creator=self.user,
            publication=self.publication,
            category=self.category,
            system_overridable_category=True,
            url="https://example.com/code",
            status=CodeArchiveUrl.STATUS.available,
        )
        data = self.publication_data()
        data["code_archive_urls"] = []
        serializer = PublicationSerializer(self.publication, data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        serializer.save(user=self.user)

        self.assertFalse(CodeArchiveUrl.objects.filter(id=archive_url.id).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                table="codearchiveurl", action="DELETE", row_id=archive_url.id
            ).exists()
        )

    def test_save_code_archive_urls_reject_foreign_publication_url(self):
        other_publication = Publication.objects.create(
            title="Other publication", added_by=self.user, container=self.container
        )
        archive_url = CodeArchiveUrl.objects.create(
            creator=self.user,
            publication=other_publication,
            category=self.category,
            system_overridable_category=True,
            url="https://example.com/other",
            status=CodeArchiveUrl.STATUS.available,
        )
        data = self.publication_data()
        data["code_archive_urls"] = [
            {
                **self.archive_url_data("https://example.com/changed"),
                "id": archive_url.id,
            }
        ]
        serializer = PublicationSerializer(self.publication, data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.assertRaises(CodeArchiveUrl.DoesNotExist):
            serializer.save(user=self.user)

        archive_url.refresh_from_db()
        self.assertEqual(archive_url.url, "https://example.com/other")


class ContactFormSerializerTestCase(BaseTest):
    def test_honey_pot(self):
        serializer = ContactFormSerializer(instance={})
        self.assertFalse(serializer.validate_contact_number(""))
        with self.assertRaises(serializers.ValidationError):
            serializer.validate_contact_number("foo")

    @patch("citation.serializers.time.time", return_value=10)
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
            serializer.validate(dict(security_hash=security_hash, timestamp=t + 1))


class SuggestMergeSerializerTestCase(BaseTest):
    def test_invalid_author_new_content_raises(self):
        serializer = SuggestMergeSerializer(
            data={
                "model_name": "author",
                "instances": [{"id": 1}, {"id": 2}],
                "new_content": {"given_name": "A", "orcid": ""},
                "email": "foo@example.com",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("family_name", serializer.errors)
        self.assertIn("orcid", serializer.errors)

    def test_valid_other_new_content_uses_validated_data(self):
        serializer = SuggestMergeSerializer(
            data={
                "model_name": "platform",
                "instances": [{"id": 1}, {"id": 2}],
                "new_content": {"name": "New Name"},
                "email": "foo@example.com",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["new_content"]["name"], "New Name")
