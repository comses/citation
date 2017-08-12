import re
from collections import defaultdict
from datetime import datetime, date
from typing import Dict, Optional

from dateutil.parser import parse as datetime_parse
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from django.contrib.sites.requests import RequestSite
from django.core.urlresolvers import reverse
from django.db import models, transaction
from django.db.models import F
from django.db.models import Q, IntegerField, Count, Max
from django.db.models.functions import Cast
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils.translation import ugettext_lazy as _
from django.core.cache import cache
from model_utils import Choices

from . import fields


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
    if len(labels) == 0:
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


class InvitationEmail(object):
    def __init__(self, request):
        self.request = request
        self.plaintext_template = get_template('email/invitation-email.txt')

    @property
    def site(self):
        return RequestSite(self.request)

    def get_plaintext_content(self, message, token):
        return self.plaintext_template.render({
            'invitation_text': message,
            'domain': self.site.domain,
            'token': token,
        })


class InvitationEmailTemplate(models.Model):
    name = models.CharField(max_length=64)
    text = models.TextField()
    date_added = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(User, related_name="citation_added_by")


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
    user = models.OneToOneField(User, null=True)

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


class AuthorCorrespondenceTemplate(models.Model):
    text = models.TextField(max_length=6000)
    label = models.TextField(max_length=50)


class AuthorCorrespondence(models.Model):
    date_created = models.DateTimeField(auto_now=True)
    date_responded = models.DateTimeField(blank=True, null=True)
    template = models.ForeignKey(AuthorCorrespondenceTemplate, related_name='correspondences')
    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name='correspondences')
    hash = models.CharField(max_length=255)


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
         'modelDocumentationList': [{'category': 'Code and formal descriptions', 'name': 'Source code'},
                                    {'category': 'Code and formal descriptions', 'name': 'Pseudocode'},
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
    added_by = models.ForeignKey(User, related_name='citation_added_note_set')
    deleted_on = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, related_name='citation_deleted_note_set', null=True, blank=True)
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
        primary_pub = Publication.objects.filter(is_primary=True, **kwargs)
        if prefetch:
            return primary_pub.prefetch_related('sponsors', 'platforms', 'note_set')

        return primary_pub


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
    code_archive_url = models.URLField(max_length=255, blank=True)
    contact_author_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    platforms = models.ManyToManyField(Platform, blank=True, through='PublicationPlatforms',
                                       related_name='publications')
    sponsors = models.ManyToManyField(Sponsor, blank=True, through='PublicationSponsors', related_name='publications')
    model_documentation = models.ManyToManyField(ModelDocumentation, through='PublicationModelDocumentations',
                                                 blank=True, related_name='publications')
    tags = models.ManyToManyField(Tag, through='PublicationTags', blank=True)
    added_by = models.ForeignKey(User, related_name='citation_added_publication_set')

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
                                         related_name='citation_assigned_publication_set')

    # type fields
    is_primary = models.BooleanField(default=True)

    # container specific fields
    container = models.ForeignKey(Container, related_name='publications')
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
        return bool(self.code_archive_url)

    def contributor_data(self):
        if cache.get(self.id):
            return cache.get(self.id)
        elif self.is_primary:
            audit_logs = AuditLog.objects.filter(
                Q(audit_command__action='MANUAL') & (Q(table='publication', row_id=self.id) |
                                                     Q(pub_id=self.id))) \
                .annotate(creator=F('audit_command__creator__username')).values('creator').order_by('creator')

            unique_logs = audit_logs.annotate(
                contribution=(Cast((Count('creator')) * 100 / len(audit_logs), IntegerField())),
                date_added=(Max('audit_command__date_added'))) \
                .values('creator', 'contribution', 'date_added').order_by('-date_added')
            return unique_logs

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

    def __str__(self):
        return 'id: {id} {title} {year}. {container}'.format(id=self.id, title=self.title, year=self.year_published,
                                                             container=self.container)


class AuditCommand(models.Model):
    Action = Choices(('SPLIT', _('Split Record')),
                     ('MERGE', _('Merge Records')),
                     ('LOAD', _('Load from File')),
                     ('MANUAL', _('User entered changes')))

    action = models.CharField(max_length=64, choices=Action)
    date_added = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(User, related_name="citation_creator_set",
                                help_text=_('The user who initiated this action, if any.'))
    message = models.TextField(blank=True, help_text=_('A human readable representation of the change made'))

    def save_once(self, *args, **kwargs):
        if self._state.adding:
            self.save(*args, **kwargs)

    @property
    def has_been_saved(self):
        return not self._state.adding

    class Meta:
        ordering = ['-date_added']


# No need of this Queryset manager now...need to remove it
class AuditLogQuerySet(models.QuerySet):
    def contributor_data(self, publication):
        audit_logs = self.filter(Q(table=publication._meta.model_name, row_id=publication.id) |
                                 Q(payload__data__publication_id=publication.id) & Q(audit_command__action='MANUAL')) \
            .annotate(creator=F('audit_command__creator__username')).values('creator').order_by('creator')
        total_count = audit_logs.count()
        unique_logs = audit_logs.annotate(
            contribution=(Cast((Count('creator') * 100.0 / total_count), IntegerField())),
            date_added=(Max('audit_command__date_added'))) \
            .values("creator", 'contribution', 'date_added').order_by('-date_added')

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
    pub_id = models.ForeignKey(Publication, related_name='auditlog', null=True, blank=True, db_constraint=False)
    audit_command = models.ForeignKey(AuditCommand, related_name='auditlogs')
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
    publication = models.ForeignKey(Publication, related_name='publication_authors')
    author = models.ForeignKey(Author, related_name='publication_authors')
    role = models.CharField(choices=RoleChoices, max_length=64)

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'author')


class PublicationCitations(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_citations')
    citation = models.ForeignKey(Publication, related_name='publication_citations_referenced_by')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'citation')


class PublicationModelDocumentations(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_modeldocumentations')
    model_documentation = models.ForeignKey(ModelDocumentation, related_name='publication_modeldocumentations')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'model_documentation')


class PublicationPlatforms(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_platforms')
    platform = models.ForeignKey(Platform, related_name='publications_platforms')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'platform')


class PublicationSponsors(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_sponsors')
    sponsor = models.ForeignKey(Sponsor, related_name='publication_sponsors')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'sponsor')


class PublicationTags(AbstractLogModel):
    publication = models.ForeignKey(Publication, related_name='publication_tags')
    tag = models.ForeignKey(Tag, related_name='publication_tags')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publication', 'tag')


class RawAuthors(AbstractLogModel):
    author = models.ForeignKey(Author, related_name='raw_authors')
    raw = models.ForeignKey(Raw, related_name='raw_authors')

    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('author', 'raw')
