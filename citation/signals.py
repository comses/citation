import logging

from citation.models import Publication, ModelDocumentation, PublicationModelDocumentations, AuditCommand
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)
