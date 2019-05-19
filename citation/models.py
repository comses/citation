import copy
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, date
from enum import Enum
from typing import Dict, Optional, List
from urllib3.util import parse_url

import requests
from dateutil.parser import parser as datetime_parser, parse as datetime_parse
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.cache import cache
from django.core.exceptions import FieldError
from django.db import models, transaction
from django.db.models import F
from django.db.models import Q, IntegerField, Count, Max
from django.db.models.functions import Cast
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from model_utils import Choices

from . import fields
from .graphviz.globals import CacheNames
from .util import send_markdown_email

logger = logging.getLogger(__name__)


def datetime_json_serialize(datetime_obj: Optional[datetime]):
    return str(datetime_obj)


def date_json_serialize(date_obj: Optional[date]):
    return str(date_obj)


def identity_json_serialize(obj):
    return obj


DISPATCH_JSON_SERIALIZE = defaultdict(lambda: identity_json_serialize,
                                      DateTimeField=datetime_json_serialize,
                                      DateField=date_json_serialize)


def json_serialize(field_type, obj):
    return DISPATCH_JSON_SERIALIZE[field_type](obj)


def make_payload(instance):
    """Make an auditlog payload for an INSERT or DELETE statement"""
    data = {}
    labels = {}
    for field in instance._meta.concrete_fields:
        data[field.attname] = json_serialize(field.get_internal_type(), getattr(instance, field.attname))
        if field.many_to_one and field.related_model != User:
            label = getattr(instance, field.name).get_message()
            labels[field.name] = label

    # this is to ensure we have at least one label for every insert and delete entry
    # TODO: isinstance check is ugly - should change interface to avoid needing it
    if len(labels) == 0 or isinstance(instance, CodeArchiveUrl):
        labels[instance._meta.model_name] = instance.get_message()
    payload = {'data': data, 'labels': labels}
    return payload


def make_versioned_payload(instance, changes: Dict):
    """Make an auditlog payload for an UPDATE statement"""
    data = {}
    labels = {}
    for column_name, new_raw_value in changes.items():
        field = instance._meta.get_field(column_name)
        old_raw_value = getattr(instance, column_name)
        old_value = json_serialize(field.get_internal_type(), old_raw_value)
        new_value = json_serialize(field.get_internal_type(), new_raw_value)
        if new_value != old_value:
            data[field.name] = {'old': old_value, 'new': new_value}
            if field.many_to_one and field.related_model != User:
                old_label = getattr(instance, field.name).get_message()
                new_label = field.related_model.objects.get(id=new_value).get_message()
                labels[field.name] = \
                    {'old': old_label, 'new': new_label}

    # this is to ensure that if changes occur we have at least one label
    if data and not labels:
        labels[instance._meta.model_name] = instance.get_message()
    if data or labels:
        payload = {'data': data, 'labels': labels}
    else:
        payload = None
    return payload


class LogManager(models.Manager):
    use_for_related_fields = True

    def log_create(self, audit_command: 'AuditCommand', **kwargs):
        with transaction.atomic():
            instance = self.create(**kwargs)
            audit_command.save_once()
            AuditLog.objects.create(
                action='INSERT',
                row_id=instance.id,
                table=instance._meta.model_name,
                payload=make_payload(instance),
                audit_command=audit_command)
            return instance

    def log_get_or_create(self, audit_command: 'AuditCommand', **kwargs):
        # relation_fields = {relation.attname for relation in self.model._meta.many_to_many}
        publication = None
        if 'publication' in kwargs:
            publication = kwargs.pop('publication')
        defaults = kwargs.pop('defaults', {})
        with transaction.atomic():
            instance, created = self.get_or_create(defaults=defaults, **kwargs)
            if created:
                action = 'INSERT'
                payload = make_payload(instance)
                row_id = instance.id
                pub_id = publication
            else:
                defaults.update(kwargs)
                action = 'UPDATE'
                payload = make_versioned_payload(instance, kwargs)
                row_id = instance.id
                pub_id = publication
            if created or payload:
                audit_command.save_once()
                AuditLog.objects.create(
                    action=action,
                    row_id=row_id,
                    table=instance._meta.model_name,
                    payload=payload,
                    pub_id=pub_id,
                    audit_command=audit_command)

        return instance, created


class LogQuerySet(models.QuerySet):
    def log_delete(self, audit_command: 'AuditCommand'):
        # TODO test synchronization with solr
        """
        batch delete
        does not keep solr index in sync. must resync solr index after calling this method
        """
        with transaction.atomic():
            instances = self.all()
            audit_command.save_once()
            auditlogs = []
            for instance in instances:
                payload = make_payload(instance)
                if payload:
                    auditlogs.append(AuditLog(
                        action='DELETE',
                        row_id=instance.id,
                        table=instance._meta.model_name,
                        payload=payload,
                        audit_command=audit_command))

            AuditLog.objects.bulk_create(auditlogs)
            instances.delete()

    def log_update(self, audit_command: 'AuditCommand', **kwargs):
        """batch update
        does not keep solr index in sync. must resync solr index after calling this method
        """
        auditlogs = []
        with transaction.atomic():
            instances = self.all()
            audit_command.save_once()
            for instance in instances:
                versioned_payload = make_versioned_payload(instance, kwargs)
                if versioned_payload:
                    auditlogs.append(AuditLog(
                        action='UPDATE',
                        row_id=instance.id,
                        table=instance._meta.model_name,
                        payload=versioned_payload,
                        audit_command=audit_command))

            AuditLog.objects.bulk_create(auditlogs)
            instances.update(**kwargs)


class AbstractLogModel(models.Model):
    """
    Class that implements logging for all children
    Subclasses should implement a get_message() method
    XXX: consider replacing get_message with simpler __str__ representation?
    """

    def get_message(self):
        raise NotImplementedError("get_message must be implemented")

    def log_delete(self, audit_command: 'AuditCommand'):
        with transaction.atomic():
            payload = make_payload(self)
            audit_command.save_once()
            AuditLog.objects.create(
                action='DELETE',
                row_id=self.id,
                table=self._meta.model_name,
                payload=payload,
                audit_command=audit_command)
            info = self.delete()
            return info

    def log_update(self, audit_command: 'AuditCommand', **kwargs):
        with transaction.atomic():
            payload = make_versioned_payload(self, kwargs)
            row_id = self.id
            if payload:
                audit_command.save_once()
                AuditLog.objects.create(
                    action='UPDATE',
                    row_id=row_id,
                    table=self._meta.model_name,
                    payload=payload,
                    audit_command=audit_command)
                for column in kwargs:
                    setattr(self, column, kwargs[column])
                self.save()
            return self

    objects = LogManager.from_queryset(LogQuerySet)()

    class Meta:
        abstract = True


class InvitationEmailTemplate(models.Model):
    """ This can probably be removed """
    name = models.CharField(max_length=64)
    text = models.TextField()
    date_added = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(User, related_name="citation_added_by", on_delete=models.PROTECT)


class Author(AbstractLogModel):
    INDIVIDUAL = 'INDIVIDUAL'
    ORGANIZATION = 'ORGANIZATION'
    TYPE_CHOICES = Choices(
        (INDIVIDUAL, _('individual')),
        (ORGANIZATION, _('organization')),
    )
    type = models.TextField(choices=TYPE_CHOICES, default=INDIVIDUAL, max_length=64)
    given_name = models.CharField(max_length=200)
    family_name = models.CharField(max_length=200)
    orcid = fields.NonEmptyTextField(max_length=200, unique=True)
    researcherid = fields.NonEmptyTextField(max_length=100, unique=True)
    email = models.EmailField(blank=True)
    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this model was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this model was last modified on this system'))

    def __str__(self):
        return '{0} {1}.'.format(self.given_name, self.family_name)

    def __repr__(self):
        return "Author(id={id}, orcid={orcid}, email={email}, given_name={given_name}, family_name={family_name})" \
            .format(id=self.id, orcid=repr(self.orcid), given_name=repr(self.given_name),
                    family_name=repr(self.family_name), email=repr(self.email))

    @property
    def name(self):
        if self.family_name:
            if self.given_name:
                return self.given_name + ' ' + self.family_name
            else:
                return self.family_name
        return self.given_name

    @property
    def given_name_initial(self):
        return self.given_name[0] if self.given_name else ''

    @staticmethod
    def normalize_author_name(author_str: str):
        normalized_name = re.sub(r"\n|\r", " ", author_str.strip())
        normalized_name = re.sub(r"\.|,|\{|\}", "", normalized_name)
        normalized_name_split = normalized_name.split(' ', 1)
        if len(normalized_name_split) == 2:
            family, given = normalized_name_split
        else:
            family, given = normalized_name, ''
        return family, given

    def get_message(self):
        return '{} {} ({})'.format(self.given_name, self.family_name, self.id)

    def duplicates(self, **kwargs):
        query = Author.objects \
            .filter((Q(orcid=self.orcid) & Q(orcid__isnull=False)) |
                    (Q(researcherid=self.researcherid) & Q(researcherid__isnull=False))) \
            .filter(**kwargs) \
            .exclude(id=self.id)
        return query


class AuthorAlias(AbstractLogModel):
    # Authors that are not an individual only have a given name
    given_name = models.CharField(max_length=200)
    family_name = models.CharField(max_length=200)

    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name="author_aliases")

    @property
    def name(self):
        if self.family_name:
            if self.given_name:
                return self.given_name + ' ' + self.family_name
            else:
                return self.family_name
        return self.given_name

    def get_message(self):
        return '{} {} ({})'.format(self.given_name, self.family_name, self.id)

    def __repr__(self):
        return "AuthorAlias(id={id}, family_name={family_name}, given_name={given_name}, author_id={author_id})" \
            .format(id=self.id, family_name=repr(self.family_name), given_name=repr(self.given_name),
                    author_id=repr(self.author_id))

    class Meta:
        unique_together = ('author', 'given_name', 'family_name')


class AuthorCorrespondenceLogQuerySet(models.QuerySet):

    def create_from_publications(self, publication_qs, custom_content='', curator=None, create=True):
        author_correspondence = []
        for publication in publication_qs:
            if not publication.is_archived:
                author_correspondence.append(
                    AuthorCorrespondenceLog.from_publication(publication=publication,
                                                             content=custom_content,
                                                             curator=curator)
                )
        if create:
            self.bulk_create(author_correspondence)
        return author_correspondence


class CodeArchiveStatus(Enum):
    NOT_AVAILABLE = (1, 'Code not available',
                     'email/src-code-request-email.txt',
                     '[comses.net] request for model source code')
    NOT_IN_ARCHIVE = (2, 'Code has a currently active URL but not in a trusted digital repository',
                      'email/code-no-archive.txt',
                      '[comses.net] request for model source code')
    ARCHIVED = (3, 'Code available in archive',
                'email/code-in-archive.txt',
                '[comses.net] request for publication metadata review')

    @property
    def ordinal(self):
        return self.value[0]

    @property
    def message(self):
        return self.value[1]

    @property
    def email_template(self):
        return self.value[2]

    @property
    def email_subject(self):
        return self.value[3]

    def __lt__(self, other):
        return self.ordinal < other.ordinal

    def __gt__(self, other):
        return self.ordinal > other.ordinal

    def __str__(self):
        return self.message


class AuthorCorrespondenceLog(models.Model):
    CODE_ARCHIVE_STATUS = Choices(
        *[(s.name, s.message) for s in CodeArchiveStatus]
    )
    DELIVERY_STATUS = Choices(
        ('sent', _('Author correspondence successfully sent')),
        ('error', _('Unable to send email, see error log for details')),
        ('not_sent', _('Correspondence has not been sent yet'))
    )
    date_created = models.DateTimeField(auto_now=True)
    date_responded = models.DateTimeField(null=True)
    curator = models.ForeignKey(User, on_delete=models.PROTECT)
    publication = models.ForeignKey('Publication', on_delete=models.PROTECT)
    status = models.CharField(max_length=64, choices=CODE_ARCHIVE_STATUS)
    content = models.TextField(blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email_delivery_status = models.CharField(max_length=50, choices=DELIVERY_STATUS, default=DELIVERY_STATUS.not_sent)
    author_submitted_url = models.URLField(help_text=_('Code archive URL'), blank=True)
    author_feedback = models.TextField(help_text=_("Correspondence / feedback for comses.net"))

    objects = AuthorCorrespondenceLogQuerySet.as_manager()

    @classmethod
    def from_publication(cls, publication, content=None, curator=None):
        return AuthorCorrespondenceLog(publication=publication,
                                       content=content,
                                       curator=curator,
                                       status=publication.code_archival_status.name
                                       )

    def __str__(self):
        return 'Correspondence on {0} created on {1}: {2} (author responded? {3})'.format(
            self.publication, self.date_created, self.status, self.has_author_responded)

    @property
    def has_author_responded(self):
        return all([self.date_responded, self.author_submitted_url])

    @property
    def contact_author_name(self):
        return self.publication.contact_author_name.title()

    @property
    def contact_email(self):
        return self.publication.contact_email.lower()

    def get_status(self):
        return CodeArchiveStatus[self.status]

    def get_absolute_url(self):
        return reverse('citation:author_correspondence', kwargs=dict(uuid=self.uuid))

    def get_email_template_path(self):
        return self.get_status().email_template

    def get_email_subject(self):
        return self.get_status().email_subject

    def create_preview_email_text(self):
        return self.create_email_text(preview=True)

    def create_email_text(self, request=None):
        correspondence_url = request.build_absolute_uri(self.get_absolute_url()) if request else self.get_absolute_url()
        context = dict(correspondence_url=correspondence_url, author_correspondence_log=self)
        # based on CodeArchivalStatus
        template = get_template(self.get_email_template_path())
        return template.render(context)

    def send_email(self, request=None):
        markdown_content = self.create_email_text(request=request)
        send_markdown_email(
            subject=self.get_email_subject(),
            body=markdown_content,
            to=[self.contact_email],
            bcc=[settings.DEFAULT_FROM_EMAIL]
        )


class Tag(AbstractLogModel):
    name = models.CharField(max_length=255, unique=True)
    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this model was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this model was last modified on this system'))

    def __str__(self):
        return self.name

    def get_message(self):
        return "{} ({})".format(self.name, self.id)


class ModelDocumentation(AbstractLogModel):
    CATEGORIES = [
        {'category': 'Narrative',
         'modelDocumentationList': [{'category': 'Narrative', 'name': 'ODD'},
                                    {'category': 'Narrative', 'name': 'Other Narrative'}]},
        {'category': 'Visual Relationships',
         'modelDocumentationList': [{'category': 'Visual Relationships', 'name': 'UML'},
                                    {'category': 'Visual Relationships', 'name': 'Flow charts'},
                                    {'category': 'Visual Relationships', 'name': 'Ontologies'},
                                    {'category': 'Visual Relationships', 'name': 'AORML'}]},
        {'category': 'Code and formal descriptions',
         'modelDocumentationList': [{'category': 'Code and formal descriptions', 'name': 'Pseudocode'},
                                    {'category': 'Code and formal descriptions', 'name': 'Mathematical description'}]},
    ]
    ''' common choices: UML, ODD, Word / PDF doc '''
    name = models.CharField(max_length=255, unique=True)
    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this model was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this model was last modified on this system'))

    def __str__(self):
        return "{} ({})".format(self.name, self.id)

    def get_message(self):
        return "{} ({})".format(self.name, self.id)


class Note(AbstractLogModel):
    text = models.TextField()
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)
    zotero_key = models.CharField(max_length=64, null=True, unique=True, blank=True)
    zotero_date_added = models.DateTimeField(null=True, blank=True)
    zotero_date_modified = models.DateTimeField(null=True, blank=True)
    added_by = models.ForeignKey(User, related_name='citation_added_note_set', on_delete=models.PROTECT)
    deleted_on = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, related_name='citation_deleted_note_set', null=True, blank=True,
                                   on_delete=models.SET_NULL)
    publication = models.ForeignKey('Publication', null=True, blank=True, on_delete=models.SET_NULL)

    @property
    def is_deleted(self):
        return bool(self.deleted_on)

    def get_message(self):
        return "{} ({})".format(self.text, self.id)


class Platform(AbstractLogModel):
    """ model platform, e.g, NetLogo or RePast """
    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(default='', blank=True)
    description = models.TextField(default='', blank=True)
    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this model was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this model was last modified on this system'))

    def get_message(self):
        return "{} ({})".format(self.name, self.id)

    def __str__(self):
        return self.get_message()


class Sponsor(AbstractLogModel):
    """ funding agency sponsoring this research """
    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(default='', blank=True)
    description = models.TextField(default='', blank=True)
    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this model was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this model was last modified on this system'))

    def get_message(self):
        return "{} ({})".format(self.name, self.id)

    def __str__(self):
        return self.get_message()


class Container(AbstractLogModel):
    """Canonical Container"""
    issn = fields.NonEmptyTextField(max_length=200, unique=True)
    eissn = fields.NonEmptyTextField(max_length=200, unique=True)
    type = models.TextField(max_length=1000, blank=True, default='')
    name = models.CharField(max_length=300)

    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this container was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this container was last modified on this system'))

    def __str__(self):
        return self.name

    def __repr__(self):
        return "Container(id={id}, name={name}, issn={issn}, type={type})" \
            .format(id=self.id, name=repr(self.name), issn=repr(self.issn), type=repr(self.type))

    def get_message(self):
        return 'name: {} issn: {}'.format(repr(self.name), repr(self.issn) if self.issn else '\'\'')

    def duplicates(self):
        return Container.objects \
            .filter((Q(issn=self.issn) & Q(issn__isnull=False)) |
                    (Q(eissn=self.issn) & Q(eissn__isnull=False)) |
                    (Q(name=self.name) & ~Q(name=''))) \
            .exclude(id=self.id)


class ContainerAlias(AbstractLogModel):
    name = models.TextField(max_length=1000, blank=True, default='')
    container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name="container_aliases")

    def __repr__(self):
        return "ContainerAlias(name={name}, container={container})" \
            .format(name=repr(self.name), container=repr(self.container))

    def get_message(self):
        return "{} ({})".format(self.name, self.id)

    class Meta:
        unique_together = ('container', 'name')


class PublicationQuerySet(models.QuerySet):

    def primary(self, prefetch=False, **kwargs):
        if 'is_primary' in kwargs:
            kwargs.pop('is_primary')
        primary_pub = self.filter(is_primary=True, **kwargs)
        if prefetch:
            return primary_pub.prefetch_related('sponsors', 'platforms', 'note_set')

        return primary_pub

    def reviewed(self):
        return self.filter(status='REVIEWED')

    def annotate_code_availability(self):
        """
        A publication is considered to have its code available if has at least one CodeArchiveUrl and all its
        CodeArchiveUrls are available
        """
        return self.prefetch_related('code_archive_urls').annotate(
            n_available_code_archive_urls=models.Count(
                'code_archive_urls',
                filter=models.Q(code_archive_urls__status='available')))

    def aggregated_list(self, identifier=None, **kwargs):
        """
        :param: identifier: String - relation identifier - should be Django Model that has name attribute (field)
                            example: sponsors, platforms, or container(i.e: journal)
        :param: kwargs: Dict - additional query filter
        :return: list of the aggregated data for the specified identifier
        """
        if identifier in ["sponsors", "platforms", "container"]:
            return self.primary(prefetch=True, **kwargs).annotate(
                name=F(identifier + '__name')).values('name').order_by(
                'name').annotate(published_count=Count('name'),
                                 code_availability_count=models.Sum(
                                     models.Case(models.When(~Q(code_archive_url=''), then=1),
                                                 default=0, output_field=models.IntegerField()))) \
                .values('name', 'published_count', 'code_availability_count').order_by('-published_count')
        return None

    def get_top_records(self, attribute=None, number=10):
        """
        :param: attribute: String - can be any valid publication model attribute (field)
                                    example: pk, sponsors, sponsors__name, or container
        :param: number: int - specifies how many record it should return
        :return: list of top data for the specified attribute
        """
        if attribute is None:
            return list(Publication.objects.filter(is_primary=True, status="REVIEWED")[:number])
        try:
            records = self.primary(status="REVIEWED").values(attribute).order_by(
                attribute).annotate(count=Count(attribute)).values(
                'count', attribute).order_by('-count')[:number]
            return [record[attribute] for record in records]
        except FieldError:
            return FieldError

    def has_no_archive_urls(self):
        return self.annotate(code_archive_urls_count=models.Count('code_archive_urls')).filter(
            code_archive_urls_count=0)

    def has_unavailable_archive_urls(self):
        return self.annotate(unavailable_archive_urls=models.Count('code_archive_urls', filter=models.Q(
            code_archive_urls__status='unavailable')))

    def no_code_available(self, **kwargs):
        return self.primary(**kwargs).reviewed().with_code_availability_counts().filter(has_available_code=False)

    def by_code_archive_url_status(self, status, count=10, contact_email=None, **kwargs):
        """ status is assumed to be one of the AuthorCorrespondenceLog.CODE_ARCHIVE_STATUS Choices """
        qs = self.primary(**kwargs).reviewed().exclude(contact_email__exact='')
        if contact_email:
            qs = qs.filter(contact_email=contact_email)
        if status == AuthorCorrespondenceLog.CODE_ARCHIVE_STATUS.NOT_AVAILABLE:
            qs = qs.with_code_availability_counts().filter(has_available_code=False)
        elif status == AuthorCorrespondenceLog.CODE_ARCHIVE_STATUS.NOT_IN_ARCHIVE:
            qs = qs.has_unavailable_archive_urls()
        elif status == AuthorCorrespondenceLog.CODE_ARCHIVE_STATUS.ARCHIVED:
            qs = qs.with_code_availability_counts().filter(has_available_code=True)
        else:
            raise ValueError("invalid status: " + status)
        qs = qs.exclude(pk__in=list(AuthorCorrespondenceLog.objects.values_list('publication', flat=True)))
        return qs[:count]

    def with_code_availability_counts(self):
        return self.annotate(available_code_archive_urls_count=models.Count(
            'code_archive_urls',
            filter=models.Q(code_archive_urls__status='available') | models.Q(code_archive_urls__status='restricted'))) \
            .annotate(unavailable_code_archive_urls_count=models.Count(
            'code_archive_urls',
            filter=models.Q(code_archive_urls__status='unavailable'))) \
            .annotate(has_available_code=models.Case(
            models.When(models.Q(available_code_archive_urls_count__gt=0) &
                        models.Q(unavailable_code_archive_urls_count=0),
                        then=models.Value(True)),
            default=models.Value(False),
            output_field=models.BooleanField()))


class Publication(AbstractLogModel):
    Status = Choices(
        ('UNREVIEWED', _('Not reviewed: Has not been reviewed by CoMSES')),
        ('AUTHOR_UPDATED', _('Updated by author: Awaiting CoMSES review')),
        ('INVALID', _('Not applicable: Publication does not refer to a specific computational model')),
        ('REVIEWED', _('Reviewed: Publication metadata reviewed and verified by CoMSES')),
    )

    # zotero publication metadata
    title = models.TextField()
    abstract = models.TextField(blank=True)
    short_title = models.CharField(max_length=255, blank=True)
    zotero_key = models.CharField(max_length=64, null=True, unique=True, blank=True)
    url = models.URLField(blank=True)
    date_published_text = models.CharField(max_length=64, blank=True)
    date_accessed = models.DateField(null=True, blank=True)
    # FIXME: remove unused Zotero metadata at some point since we are no longer importing from Zotero
    archive = models.CharField(max_length=255, blank=True)
    archive_location = models.CharField(max_length=255, blank=True)
    library_catalog = models.CharField(max_length=255, blank=True)
    call_number = models.CharField(max_length=255, blank=True)
    rights = models.CharField(max_length=255, blank=True)
    extra = models.TextField(blank=True)
    published_language = models.CharField(max_length=255, default='English', blank=True)
    zotero_date_added = models.DateTimeField(help_text=_('date added field from zotero'), null=True, blank=True)
    zotero_date_modified = models.DateTimeField(help_text=_('date modified field from zotero'), null=True, blank=True)
    creators = models.ManyToManyField(Author, related_name='publications', through='PublicationAuthors')

    # custom incoming tags set by zotero data entry to mark the code archive url, contact author's email, the ABM platform
    # used, research sponsors (funding agencies, etc.), documentation, and other research keyword tags
    contact_author_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    platforms = models.ManyToManyField(Platform, blank=True, through='PublicationPlatforms',
                                       related_name='publications')
    sponsors = models.ManyToManyField(Sponsor, blank=True, through='PublicationSponsors', related_name='publications')
    model_documentation = models.ManyToManyField(ModelDocumentation, through='PublicationModelDocumentations',
                                                 blank=True, related_name='publications')
    tags = models.ManyToManyField(Tag, through='PublicationTags', blank=True, related_name='publications')
    added_by = models.ForeignKey(User, related_name='citation_added_publication_set', on_delete=models.PROTECT)

    # custom fields used by catalog internally
    status = models.CharField(choices=Status, max_length=64, default=Status.UNREVIEWED)
    flagged = models.BooleanField(default=False)
    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this publication was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this publication was last modified on this system'))

    author_comments = models.TextField(blank=True)
    email_sent_count = models.PositiveIntegerField(default=0)
    assigned_curator = models.ForeignKey(User,
                                         null=True,
                                         blank=True,
                                         help_text=_("Currently assigned curator"),
                                         related_name='citation_assigned_publication_set',
                                         on_delete=models.SET_NULL)

    # type fields
    is_primary = models.BooleanField(default=True)

    # container specific fields
    container = models.ForeignKey(Container, related_name='publications', on_delete=models.PROTECT)
    pages = models.CharField(max_length=255, default='', blank=True)
    issn = models.CharField(max_length=255, default='', blank=True)
    volume = models.CharField(max_length=255, default='', blank=True)
    issue = models.CharField(max_length=255, default='', blank=True)
    series = models.CharField(max_length=255, default='', blank=True)
    series_title = models.CharField(max_length=255, default='', blank=True)
    series_text = models.CharField(max_length=255, default='', blank=True)
    doi = fields.NonEmptyTextField(max_length=255, unique=True)
    isi = fields.NonEmptyTextField(max_length=255, unique=True)

    citations = models.ManyToManyField(
        "self", symmetrical=False, related_name="referenced_by",
        through='PublicationCitations', through_fields=('publication', 'citation'))

    objects = LogManager.from_queryset(LogQuerySet)()
    api = PublicationQuerySet.as_manager()

    def duplicates(self, query=None, **kwargs):
        if query is None:
            query = Publication.objects \
                .filter((Q(isi=self.isi) & Q(isi__isnull=False)) |
                        (Q(doi=self.doi) & Q(doi__isnull=False)) |
                        (Q(date_published_text__iexact=self.date_published_text) &
                         ~Q(date_published_text='') &
                         Q(title__iexact=self.title) &
                         ~Q(title=''))) \
                .exclude(id=self.id)

        return query.filter(**kwargs)

    def get_message(self):
        return "{} ({})".format(self.title, self.id)

    def is_editable_by(self, user):
        # eventually consider having permission groups or per-object permissions
        return self.assigned_curator == user

    @property
    def is_archived(self):
        return self.code_archive_urls.exclude(status=CodeArchiveUrl.STATUS.unavailable).exists()

    @property
    def code_archival_status(self):
        return self.code_archive_urls.code_archive_status()

    @transaction.atomic
    def flag(self, message: str, submitter: User):
        self.flagged = True
        self.note_set.add(text=message, added_by=submitter)
        self.save()

    @property
    def contributor_data_cache_key(self):
        return "{0}{1}".format(CacheNames.CONTRIBUTION_DATA.value, self.pk)

    def contributor_data(self, latest=False):
        value = cache.get(self.contributor_data_cache_key)
        if value is not None and not latest:
            return value
        elif self.is_primary:
            logs = AuditLog.objects.get_contributor_data(self)
            cache.set(self.contributor_data_cache_key, list(logs), 86410)
            return logs
        return []

    @property
    def slug(self):
        year_str = None
        if self.year_published is not None:
            year_str = str(self.year_published)
        apa_authors = '-'.join(['{0} {1}'.format(c.given_name, c.family_name) for c in self.creators.all()])
        slug_text = self.slugify_max("-".join([x for x in [apa_authors, year_str, self.title] if x]), 100)
        return slug_text

    def slugify_max(self, text, max_length=50):
        slug = slugify(text)
        if len(slug) <= 0:
            return "-"
        if len(slug) <= max_length:
            return slug
        trimmed_slug = slug[:max_length].rsplit('-', 1)[0]
        if len(trimmed_slug) <= max_length:
            return trimmed_slug
        # First word is > max_length chars, so we have to break it
        return slug[:max_length]

    def _pk_url(self, name):
        return reverse(name, args=(self.pk, self.slug))

    def get_absolute_url(self):
        return self._pk_url('citation:publication_detail')

    @property
    def incomplete_date_published(self):
        r = datetime_parser()._parse(self.date_published_text)[0]
        has_year = r is not None and r.year is not None
        if has_year:
            has_month = r.month is not None
            if has_month:
                has_day = r.day is not None
                if has_day:
                    return f'{r.year}-{r.month:02d}-{r.day:02d}'
                return f'{r.year}-{r.month:02d}'
            return f'{r.year}'
        return ''

    @property
    def date_published(self):
        try:
            return datetime_parse(self.date_published_text).date()
        except ValueError:
            return None

    @property
    def year_published(self):
        try:
            return int(datetime_parse(self.date_published_text).year)
        except ValueError:
            return None

    @property
    def container_title(self):
        return self.container.name.title() if self.container else 'None'

    def apa_citation_string(self):
        apa_authors = ', '.join(['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in self.creators.all()])
        return "{0} ({1}). {2}. {3}, {4}({5})".format(
            apa_authors,
            self.year_published,
            self.title,
            self.container_title,
            self.volume,
            self.pages
        )

    def get_public_detail_url(self):
        # FIXME: this refers to catalog urls...
        return reverse('core:public-publication-detail', kwargs={'pk': self.pk})

    def __str__(self):
        return 'id: {id} {title} {year}. {container}'.format(id=self.id, title=self.title, year=self.year_published,
                                                             container=self.container)


class CodeArchiveUrlCategory(models.Model):
    category = models.CharField(max_length=150)
    subcategory = models.CharField(max_length=150)

    @property
    def trusted(self):
        return self.category == 'Archive'

    def __str__(self):
        return f'category={self.category} subcategory={self.subcategory}'

    def get_message(self):
        return self.__str__()

    class Meta:
        unique_together = (('category', 'subcategory'),)


class Match:
    @classmethod
    def always(cls):
        return cls(True)

    @classmethod
    def never(cls):
        return cls(False)

    def __init__(self, value):
        self.value = value

    def match(self, string):
        return self.value

    def __bool__(self):
        return self.value


class CodeArchiveUrlPatternQuerySet(models.QuerySet):
    def with_matchers(self):
        qs = self.exclude(regex_host_matcher='', regex_path_matcher='')
        patterns = list(qs)
        for pattern in patterns:
            pattern.host_matcher = re.compile(
                pattern.regex_host_matcher) if pattern.regex_host_matcher else Match.always()
            pattern.path_matcher = re.compile(
                pattern.regex_path_matcher) if pattern.regex_path_matcher else Match.always()
        return patterns


class CodeArchiveUrlPattern(models.Model):
    regex_host_matcher = models.CharField(max_length=800)
    regex_path_matcher = models.CharField(max_length=800)
    category = models.ForeignKey(CodeArchiveUrlCategory, on_delete=models.PROTECT)

    objects = CodeArchiveUrlPatternQuerySet.as_manager()

    def __str__(self):
        return f'category={self.category_id} regex_host_matcher={repr(self.regex_host_matcher)} regex_path_matcher={repr(self.regex_path_matcher)}'


class CodeArchiveUrlQuerySet(LogQuerySet):

    def active(self, **kwargs):
        return self.filter(is_active=True, **kwargs)

    def code_archive_status(self, **kwargs):
        aggregate_status = None
        qs = self.active(**kwargs)
        if qs.exists():
            for code_archive_url in self.active(**kwargs):
                url_status = code_archive_url.code_archive_status
                if aggregate_status is None or aggregate_status < url_status:
                    aggregate_status = url_status
            return aggregate_status

        return CodeArchiveStatus.NOT_AVAILABLE


class CodeArchiveUrl(AbstractLogModel):
    STATUS = Choices(
        ('available', _('Available: Codebase is currently openly accessible at the specified URL')),
        ('restricted', _('Restricted: Specified URL is locked behind authentication or paywall')),
        ('unavailable', _('Unavailable: No URL available or URL does not resolve'))
    )

    publication = models.ForeignKey(Publication, on_delete=models.PROTECT, related_name='code_archive_urls')

    date_created = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True,
                                    help_text=_("True if this Archive URL is not defunct, i.e., has been replaced."))
    notes = models.TextField(blank=True, help_text=_("Remarks on this URL from the author or curator"))

    url = models.URLField(blank=True, max_length=2000)
    category = models.ForeignKey(CodeArchiveUrlCategory, related_name='code_archive_urls', on_delete=models.PROTECT)
    status = models.CharField(choices=STATUS, max_length=100)
    system_overridable_category = models.BooleanField(
        default=True,
        help_text=_("Signifies that this URL's category can be overridden (i.e., not user entered).")
    )
    creator = models.ForeignKey(User, on_delete=models.PROTECT)

    api = CodeArchiveUrlQuerySet.as_manager()

    @property
    def code_archive_status(self):
        if self.status == CodeArchiveUrl.STATUS.available and self.category.trusted:
            return CodeArchiveStatus.ARCHIVED
        elif self.status == CodeArchiveUrl.STATUS.restricted:
            return CodeArchiveStatus.NOT_IN_ARCHIVE
        else:
            return CodeArchiveStatus.NOT_AVAILABLE

    def check_status(self, patterns, fallback_category):
        url = self.url
        category = CodeArchiveUrl.categorize_url(url, patterns, fallback_category=fallback_category)
        try:
            # HEAD requests hang on some URLs so using GET for now
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            self.add_url_status_log(category, response)
        except requests.exceptions.RequestException as err:
            self.add_url_status_log(category, err.response)

    def add_url_status_log(self, category, response):
        response_status = CodeArchiveUrl.get_status_choice(response) # corresponds to the status Choices

        URLStatusLog.objects.create(status_code=response.status_code,
                                    publication=self.publication,
                                    status_reason=response.reason, headers=response.headers,
                                    url=self.url)
        changes = {}
        if self.status != response_status:
            changes['status'] = {'old': self.status, 'new': response_status}
            self.status = response_status
        if self.system_overridable_category and self.category != category:
            changes['category'] = {'old': self.category, 'new': category}
            self.category = category
        if changes:
            logger.info('URL status (%s): %s %s', self.publication.title[:25], self.url, changes)
            self.save()

    @classmethod
    def get_status_choice(cls, response):
        # FIXME: consider doing more fine-grained checking on the response
        if response:
            return CodeArchiveUrl.STATUS.available
        elif response.status_code == 403:
            return CodeArchiveUrl.STATUS.restricted
        else:
            return CodeArchiveUrl.STATUS.unavailable

    @classmethod
    def categorize_url(cls, url, patterns, fallback_category):
        """
        Categorize the url depending on the server name into following categories
        CoMSES, Open Source, Platforms, Journal, Personal, Others, and Invalid
        """
        parsed_url = parse_url(url)
        host = parsed_url.host
        path = parsed_url.path

        for pattern in patterns:
            host_matcher = pattern.host_matcher
            path_matcher = pattern.path_matcher

            if host_matcher.match(host) and path_matcher.match(path):
                logger.info('Categorized url %s as %s', url, pattern.category)
                return pattern.category
        logger.info('Categorized url %s as %s', url, fallback_category)
        return fallback_category

    @property
    def is_available(self):
        return self.status in (self.STATUS.available, self.STATUS.restricted)

    @property
    def category_name(self):
        return f'{self.category.category} / {self.category.subcategory}' if self.category.subcategory else self.category.category

    def __str__(self):
        return f'url={self.url} {self.category} status={self.status} creator={self.creator}'

    def get_message(self):
        return self.__str__()


class URLStatusLog(models.Model):
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT)

    url = models.URLField(blank=True, max_length=2000)
    date_created = models.DateTimeField(auto_now_add=True,
                                        help_text=_('Date this url was last verified'))
    last_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this url status was last modified on this system'))
    headers = models.TextField(blank=True, help_text=_('contains information about the url header'))
    status_code = models.PositiveIntegerField(default=0)
    status_reason = models.TextField(blank=True, help_text=_('contains reason for the url success/failure'))
    system_generated = models.BooleanField(default=True)

    def get_message(self):
        return "Pub: {pub} {url} {code} {reason}".format(pub=self.publication,
                                                         url=self.url,
                                                         code=self.status_code,
                                                         reason=self.status_reason)


class AuditCommand(models.Model):
    Action = Choices(('SPLIT', _('Split Record')),
                     ('MERGE', _('Merge Records')),
                     ('LOAD', _('Load from File')),
                     ('MANUAL', _('User entered changes')))

    action = models.CharField(max_length=64, choices=Action)
    date_added = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(User, related_name="citation_creator_set",
                                help_text=_('The user who initiated this action, if any.'), on_delete=models.PROTECT)
    message = models.TextField(blank=True, help_text=_('A human readable representation of the change made'))

    def save_once(self, *args, **kwargs):
        if self._state.adding:
            self.save(*args, **kwargs)

    @property
    def has_been_saved(self):
        return not self._state.adding

    @classmethod
    def init_merge(cls, creator, message=''):
        return AuditCommand(action='MERGE', creator=creator, message=message)

    class Meta:
        ordering = ['-date_added']


class AuditLogQuerySet(models.QuerySet):

    def get_contributor_data(self, publication):
        audit_logs = AuditLog.objects.filter(
            Q(audit_command__action='MANUAL') & (Q(table=publication._meta.model_name, row_id=publication.id) |
                                                 Q(pub_id=publication.id))) \
            .annotate(creator=F('audit_command__creator__username')).values('creator').order_by('creator')

        unique_logs = audit_logs.annotate(
            contribution=(Cast((Count('creator')) * 100 / len(audit_logs), IntegerField())),
            date_added=(Max('audit_command__date_added'))) \
            .values('creator', 'contribution', 'date_added').order_by('-date_added')

        return unique_logs


class AuditLog(models.Model):
    # TODO: may want to add a generic foreign key to table, row_id combination
    Action = Choices(('UPDATE', _('Update')),
                     ('INSERT', _('Insert')),
                     ('DELETE', _('Delete')))
    action = models.CharField(max_length=64, choices=Action)
    row_id = models.BigIntegerField()
    table = models.CharField(max_length=128)
    payload = JSONField(blank=True, null=True,
                        help_text=_('A JSON dictionary containing modified fields, if any, for the given publication'))
    pub_id = models.ForeignKey(Publication, related_name='auditlog', null=True, blank=True, db_constraint=False,
                               on_delete=models.DO_NOTHING)
    audit_command = models.ForeignKey(AuditCommand, related_name='auditlogs', on_delete=models.CASCADE)
    message = models.CharField(max_length=2000, blank=True)
    objects = AuditLogQuerySet.as_manager()

    def __str__(self):
        return u"{} performed {} on {}".format(
            self.action,
            self.message,
            self.payload,
        )

    @property
    def creator(self):
        return self.audit_command.creator

    def _generate_through_message(self):
        pass

    def _generate_message(self):
        pass

    def generate_message(self):
        for key, value in self.payload.items():
            if isinstance(value, dict):
                pass

    class Meta:
        ordering = ['-id']


class Raw(AbstractLogModel):
    BIBTEX_FILE = "BIBTEX_FILE"
    BIBTEX_ENTRY = "BIBTEX_ENTRY"
    BIBTEX_REF = "BIBTEX_REF"
    CROSSREF_DOI_SUCCESS = "CROSSREF_DOI_SUCCESS"
    CROSSREF_DOI_FAIL = "CROSSREF_DOI_FAIL"
    CROSSREF_SEARCH_SUCCESS = "CROSSREF_SEARCH_SUCCESS"
    CROSSREF_SEARCH_FAIL_NOT_UNIQUE = "CROSSREF_SEARCH_FAIL_NOT_UNIQUE"
    CROSSREF_SEARCH_FAIL_OTHER = "CROSSREF_SEARCH_FAIL_OTHER"
    CROSSREF_SEARCH_CANDIDATE = "CROSSREF_SEARCH_CANDIDATE"

    SOURCE_CHOICES = Choices(
        (BIBTEX_FILE, "BibTeX File"),
        (BIBTEX_ENTRY, "BibTeX Entry"),
        (BIBTEX_REF, "BibTeX Reference"),
        (CROSSREF_DOI_SUCCESS, "CrossRef lookup succeeded"),
        (CROSSREF_DOI_FAIL, "CrossRef lookup failed"),
        (CROSSREF_SEARCH_SUCCESS, "CrossRef search succeeded"),
        (CROSSREF_SEARCH_FAIL_NOT_UNIQUE, "CrossRef search failed - not unique"),
        (CROSSREF_SEARCH_FAIL_OTHER, "CrossRef search failed - other"),
        (CROSSREF_SEARCH_CANDIDATE, "CrossRef search match candidate")
    )
    key = models.TextField(choices=SOURCE_CHOICES, max_length=100)
    value = JSONField()

    publication = models.ForeignKey(Publication, related_name='raw', on_delete=models.PROTECT)
    container = models.ForeignKey(Container, related_name='raw', on_delete=models.PROTECT)
    authors = models.ManyToManyField(Author, related_name='raw', through='RawAuthors')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    def get_message(self):
        return '{} ({})'.format(self.key, self.id)

    def __str__(self):
        return "Raw {key}, {id}".format(key=self.key, id=self.id)


class PublicationAuthors(AbstractLogModel):
    RoleChoices = Choices(
        ('AUTHOR', _('author')),
        ('REVIEWED_AUTHOR', _('reviewed author')),
        ('CONTRIBUTOR', _('contributor')),
        ('EDITOR', _('editor')),
        ('TRANSLATOR', _('translator')),
        ('SERIES_EDITOR', _('series editor')),
    )
    publication = models.ForeignKey(Publication, related_name='publication_authors', on_delete=models.CASCADE)
    author = models.ForeignKey(Author, related_name='publication_authors', on_delete=models.CASCADE)
    role = models.CharField(choices=RoleChoices, max_length=64)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'author')


class PublicationCitations(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_citations', on_delete=models.CASCADE)
    citation = models.ForeignKey(Publication, related_name='publication_citations_referenced_by',
                                 on_delete=models.CASCADE)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'citation')


class PublicationModelDocumentations(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_modeldocumentations',
                                    on_delete=models.CASCADE)
    model_documentation = models.ForeignKey(ModelDocumentation, related_name='publication_modeldocumentations',
                                            on_delete=models.CASCADE)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'model_documentation')


class PublicationPlatforms(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_platforms', on_delete=models.CASCADE)
    platform = models.ForeignKey(Platform, related_name='publication_platforms', on_delete=models.CASCADE)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'platform')


class PublicationSponsors(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_sponsors', on_delete=models.CASCADE)
    sponsor = models.ForeignKey(Sponsor, related_name='publication_sponsors', on_delete=models.CASCADE)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'sponsor')


class PublicationTags(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_tags', on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, related_name='publication_tags', on_delete=models.CASCADE)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'tag')


class RawAuthors(AbstractLogModel):
    author = models.ForeignKey(Author, related_name='raw_authors', on_delete=models.CASCADE)
    raw = models.ForeignKey(Raw, related_name='raw_authors', on_delete=models.CASCADE)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('author', 'raw')


class Submitter(models.Model):
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    email = models.EmailField(blank=True)

    def get_email(self):
        return self.email if self.email else self.user.email

    @classmethod
    def get_or_create(cls, user: User, email):
        if user.is_anonymous:
            return Submitter.objects.get_or_create(email=email)
        else:
            return Submitter.objects.get_or_create(user=user)

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return f'<Submitter: user={self.user}>' if self.user else f'<Submitter: email={self.email}>'


class SuggestedPublication(models.Model):
    doi = fields.NonEmptyTextField(max_length=255, unique=True, verbose_name=_('DOI'), blank=True)
    title = models.TextField(default='', blank=True)
    journal = models.TextField(default='', blank=True)
    volume = models.CharField(max_length=255, default='', blank=True)
    issue = models.CharField(max_length=255, default='', blank=True)
    pages = models.CharField(max_length=255, default='', blank=True)
    authors = models.CharField(max_length=300, default='', blank=True)
    submitter = models.ForeignKey(Submitter, on_delete=models.PROTECT)
    code_archive_url = models.URLField(max_length=255, blank=True)

    @property
    def short_name(self):
        name = []
        if self.title:
            name.append(self.title)
        if self.doi:
            name.append('DOI: {}'.format(self.doi))
        return ' '.join(name)


class SuggestedMerge(AbstractLogModel):
    content_type = models.ForeignKey(
        ContentType, related_name='suggested_merge_set', on_delete=models.PROTECT,
        limit_choices_to=models.Q(app_label='citation') & models.Q(
            model__in=[m._meta.model_name for m in (Author, Container, Platform, Publication, Sponsor)]))
    duplicates = ArrayField(models.IntegerField())
    new_content = JSONField()
    creator = models.ForeignKey(Submitter, related_name='suggested_merge_set', on_delete=models.PROTECT)
    comment = models.CharField(max_length=1000, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_applied = models.DateTimeField(null=True, blank=True)

    objects = LogQuerySet.as_manager()

    @classmethod
    def annotate_names(cls, instances: List['SuggestedMerge']):
        model_lookups = defaultdict(list)
        model_class_to_indices = defaultdict(list)
        for i, instance in enumerate(instances):
            model_class = instance.content_type.model_class()
            model_lookups[model_class] += instance.duplicates

            model_class_to_indices[model_class].append(i)

        for model, ids in model_lookups.items():
            pk_to_related_instances = model.objects.filter(id__in=ids).in_bulk()
            matching_instances = [instances[ind] for ind in model_class_to_indices[model]]
            for instance_match in matching_instances:
                instance_match.duplicate_instances = [pk_to_related_instances[pk] for pk in instance_match.duplicates
                                                      if pk in pk_to_related_instances]
        return instances

    @property
    def kept_pk(self):
        return self.duplicates[0]

    @property
    def discarded_pks(self):
        return self.duplicates[1:]

    def duplicate_text(self):
        model_class = self.content_type.model_class()
        bulk_instances = model_class.objects.filter(pk__in=self.duplicates).in_bulk()
        instances = bulk_instances.values()
        missing_pks = set(self.duplicates).difference(bulk_instances.keys())
        template = get_template('includes/duplicate_text.html')
        return template.render(context={'instances': instances, 'missing_pks': missing_pks})

    duplicate_text.short_description = 'Duplicates'

    def get_message(self):
        model_class = self.content_type.model_class()
        instances = model_class.objects.filter(pk__in=self.duplicates)
        return '{} with duplicates {}'.format(self.content_type, [instance.get_message() for instance in instances])

    @staticmethod
    def _move_author_aliases(kept_pk, discarded_pks, audit_command):
        kept_author_aliases = set(AuthorAlias.objects.filter(author_id=kept_pk).values_list('family_name', 'given_name'))
        author_aliases = AuthorAlias.objects.filter(author_id__in=discarded_pks)
        for author_alias in author_aliases:
            if (author_alias.family_name, author_alias.given_name) in kept_author_aliases:
                author_alias.log_delete(audit_command)
            else:
                author_alias.log_update(audit_command, author_id=kept_pk)

    @staticmethod
    def _move_raw_authors(kept_pk, discarded_pks, audit_command):
        kept_raw_ids = set(ra.raw_id for ra in RawAuthors.objects.filter(author_id=kept_pk))
        raw_authors = RawAuthors.objects.filter(author_id__in=discarded_pks)
        for raw_author in raw_authors:
            if raw_author.raw_id in kept_raw_ids:
                raw_author.log_delete(audit_command)
            else:
                raw_author.log_update(audit_command, author_id=kept_pk)

    @staticmethod
    def _move_publication_authors(kept_pk, discarded_pks, audit_command):
        kept_publication_ids = set(pa.publication_id for pa in PublicationAuthors.objects.filter(author_id=kept_pk))
        pub_authors = PublicationAuthors.objects.filter(author_id__in=discarded_pks)
        for pub_author in pub_authors:
            if pub_author.publication_id in kept_publication_ids:
                pub_author.log_delete(audit_command)
            else:
                pub_author.log_update(audit_command, author_id=kept_pk)

    @classmethod
    def merge_authors(cls, pks, content, audit_command):
        kept_author_pk = min(pks)
        discarded_author_pks = copy.deepcopy(pks)
        discarded_author_pks.remove(kept_author_pk)
        cls._move_author_aliases(kept_author_pk, discarded_author_pks, audit_command)
        cls._move_raw_authors(kept_author_pk, discarded_author_pks, audit_command)
        cls._move_publication_authors(kept_author_pk, discarded_author_pks, audit_command)
        Author.objects.filter(pk__in=discarded_author_pks).log_delete(audit_command)
        Author.objects.get(pk=kept_author_pk).log_update(audit_command, **content)

    @staticmethod
    def merge_containers(pks, content, audit_command):
        kept_container_pk = min(pks)
        discarded_container_pks = copy.deepcopy(pks)
        discarded_container_pks.remove(kept_container_pk)
        Publication.objects.filter(container__in=discarded_container_pks).log_update(audit_command,
                                                                                     container_id=kept_container_pk)
        Container.objects.filter(container__in=discarded_container_pks).log_delete(audit_command)
        Container.objects.get(pk=kept_container_pk).log_update(audit_command, **content)

    @staticmethod
    def _move_publication_platforms(kept_platform_pk, discarded_platform_pks, audit_command):
        kept_publication_pks = set(PublicationPlatforms.objects
                                   .filter(platform_id=kept_platform_pk)
                                   .values_list('publication_id', flat=True))
        publication_platforms = PublicationPlatforms.objects.filter(platform_id__in=discarded_platform_pks)
        for publication_platform in publication_platforms:
            if publication_platform.publication_id in kept_publication_pks:
                publication_platform.log_delete(audit_command)
            else:
                publication_platform.log_update(audit_command, platform_id=kept_platform_pk)

    @classmethod
    def merge_platforms(cls, pks, content, audit_command):
        kept_platform_pk = min(pks)
        discarded_platform_pks = copy.deepcopy(pks)
        discarded_platform_pks.remove(kept_platform_pk)
        cls._move_publication_platforms(kept_platform_pk=kept_platform_pk,
                                        discarded_platform_pks=discarded_platform_pks,
                                        audit_command=audit_command)
        Platform.objects.filter(pk__in=discarded_platform_pks).log_delete(audit_command)
        Platform.objects.get(pk=kept_platform_pk).log_update(audit_command, **content)

    @staticmethod
    def _move_publication_sponsors(kept_pk, discarded_pks, audit_command):
        kept_publication_pks = set(PublicationSponsors.objects
                                   .filter(sponsor_id=kept_pk)
                                   .values_list('publication_id', flat=True))
        publication_sponsors = PublicationSponsors.objects.filter(sponsor_id__in=discarded_pks)
        for publication_sponsors in publication_sponsors:
            if publication_sponsors.publication_id in kept_publication_pks:
                publication_sponsors.log_delete(audit_command)
            else:
                publication_sponsors.log_update(audit_command, sponsor_id=kept_pk)

    @classmethod
    def merge_sponsors(cls, pks, content, audit_command, message=''):
        kept_sponsor_pk = min(pks)
        discarded_sponsor_pks = copy.deepcopy(pks)
        discarded_sponsor_pks.remove(kept_sponsor_pk)
        logger.info('Moving discarded %s to %s sponsor', discarded_sponsor_pks, kept_sponsor_pk)
        cls._move_publication_sponsors(kept_pk=kept_sponsor_pk,
                                       discarded_pks=discarded_sponsor_pks,
                                       audit_command=audit_command)
        logger.info('Deleting discarded sponsors')
        Sponsor.objects.filter(pk__in=discarded_sponsor_pks).log_delete(audit_command)
        logger.info('Modifying kept sponsor')
        Sponsor.objects.get(pk=kept_sponsor_pk).log_update(audit_command, **content)

    @staticmethod
    def _move_publication_tags(kept_pk, discarded_pks, audit_command):
        kept_publication_pks = set(PublicationTags.objects
                                   .filter(tag_id=kept_pk)
                                   .values_list('publication_id', flat=True))
        publication_tags = PublicationTags.objects.filter(tag_id__in=discarded_pks)
        for publication_tag in publication_tags:
            if publication_tag.publication_id in kept_publication_pks:
                publication_tag.log_delete(audit_command)
            else:
                publication_tag.log_update(audit_command, sponsor_id=kept_pk)

    @classmethod
    def merge_tags(cls, pks, content, audit_command):
        kept_tag_pk = min(pks)
        discarded_tag_pks = copy.deepcopy(pks)
        discarded_tag_pks.remove(kept_tag_pk)
        cls._move_publication_tags(kept_pk=kept_tag_pk,
                                   discarded_pks=discarded_tag_pks,
                                   audit_command=audit_command)
        Tag.objects.filter(pk__in=discarded_tag_pks).log_delete(audit_command)
        Tag.objects.get(pk=kept_tag_pk).log_update(audit_command, **content)

    def merge(self, creator):
        assert self.date_applied is None
        assert len(self.duplicates) > 1

        model = self.content_type.model_class()
        pks = self.duplicates
        content = self.new_content
        model_merger = _MERGE_LOOKUP[model]
        with transaction.atomic():
            audit_command = AuditCommand.init_merge(creator=creator)
            model_merger(pks=pks, content=content, audit_command=audit_command)
            self.log_update(audit_command, date_applied=datetime.utcnow())
        logger.info('Merged %s with pks %s and changed content to %s', self.content_type, self.duplicates,
                    self.new_content)

    def __str__(self):
        return f'content_type={self.content_type} duplicates={self.duplicates} new_content={self.new_content} creator={self.creator}'


_MERGE_LOOKUP = {
    Author: SuggestedMerge.merge_authors,
    Container: SuggestedMerge.merge_containers,
    Platform: SuggestedMerge.merge_platforms,
    Sponsor: SuggestedMerge.merge_sponsors,
    Tag: SuggestedMerge.merge_tags
}
