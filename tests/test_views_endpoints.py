import json

from django.urls import reverse

from citation.models import AuditCommand, Note

from .test_views import PublicationDetailTest


class PublicationEndpointTest(PublicationDetailTest):
    def test_publication_list_get_returns_paginated_json(self):
        self.login("bobsmith", "test")

        response = self.client.get(
            self._json_url("citation:publications"), HTTP_ACCEPT="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("json", response.data)
        payload = json.loads(response.data["json"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["results"][0]["detail_url"], self.publication.get_absolute_url()
        )

    def test_publication_list_post_returns_validation_errors(self):
        self.login("bobsmith", "test")

        response = self.client.post(
            self._json_url("citation:publications"),
            data={"title": "Incomplete publication"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("flagged", response.data)

    def test_curator_publication_put_updates_publication_and_audits(self):
        self.login("bobsmith", "test")
        data = self._publication_payload()
        data["title"] = "Updated through endpoint"
        initial_audit_command_count = AuditCommand.objects.count()

        response = self.client.put(
            self._json_url("citation:publication_detail", self.publication.pk),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.publication.refresh_from_db()
        self.assertEqual(self.publication.title, "Updated through endpoint")
        self.assertEqual(AuditCommand.objects.count(), initial_audit_command_count + 1)

    def test_curator_publication_put_returns_validation_errors(self):
        self.login("bobsmith", "test")

        response = self.client.put(
            self._json_url("citation:publication_detail", self.publication.pk),
            data=json.dumps({"title": "Incomplete publication"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("flagged", response.data)

    def test_note_delete_soft_deletes_note(self):
        note = Note.objects.create(
            text="Needs review", added_by=self.user, publication=self.publication
        )
        self.login("bobsmith", "test")

        response = self.client.delete(reverse("citation:note_detail", args=[note.pk]))

        self.assertEqual(response.status_code, 204)
        note.refresh_from_db()
        self.assertEqual(note.deleted_by, self.user)
        self.assertIsNotNone(note.deleted_on)
        self.assertTrue(note.is_deleted)

    def _publication_payload(self):
        from citation.serializers import PublicationSerializer

        return PublicationSerializer(self.publication).data

    def _json_url(self, name, *args):
        return reverse(name, args=args)[:-1] + ".json/"
