from django.urls import reverse
from citation.models import (
    Container, Publication, PublicationPlatforms, Platform, Author, PublicationAuthors)

from .common import BaseTest

import logging

logger = logging.getLogger(__name__)


class PublicationDetailTest(BaseTest):
    def setUp(self):
        self.user = self.create_user(username='bobsmith',
                                     email='a@b.com', password='test')
        self.author = Author.objects.create(given_name='Bob', family_name='Smith', type=Author.INDIVIDUAL)
        self.container = Container.objects.create(name='JASSS')
        self.platform = Platform.objects.create(name='JVM')
        self.publication = Publication.objects.create(title='Foo', added_by=self.user, container=self.container)
        self.publication_platform = PublicationPlatforms.objects.create(
            platform=self.platform, publication=self.publication)
        self.publication_author = PublicationAuthors.objects.create(
            author=self.author, publication=self.publication, role=PublicationAuthors.RoleChoices.AUTHOR)

    def test_reverse(self):
        url = reverse('citation:publication_detail', args=[self.publication.pk])
        logger.debug("url: %s", url)
