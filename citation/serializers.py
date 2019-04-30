import logging
import time
from collections import OrderedDict, defaultdict
from hashlib import sha1
from pprint import pformat

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, pagination
from rest_framework.exceptions import ValidationError
from rest_framework.utils import model_meta

from .models import (Tag, Sponsor, Platform, Author, Publication, Container, ModelDocumentation, Note, AuditCommand,
                     AuditLog, PublicationModelDocumentations, PublicationPlatforms, PublicationSponsors,
                     CodeArchiveUrl, CodeArchiveUrlCategory, AuthorCorrespondenceLog)

logger = logging.getLogger(__name__)


class CatalogPagination(pagination.PageNumberPagination):
    # FIXME: review & refactor: http://www.django-rest-framework.org/api-guide/pagination/
    def get_paginated_response(self, data):
        return OrderedDict([
            ('start_index', self.page.start_index()),
            ('end_index', self.page.end_index()),
            ('num_pages', self.page.paginator.num_pages),
            ('current_page', self.page.number),
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ])


###########################
#    Model Serializers    #
###########################


class AuthorCorrespondenceLogSerializer(serializers.ModelSerializer):

    publication_title = serializers.ReadOnlyField(source='publication.title')
    contact_author_name = serializers.ReadOnlyField(source='publication.contact_author')

    def update(self, instance, validated_data):
        instance.date_responded = timezone.now()
        return super().update(instance, validated_data)

    class Meta:
        model = AuthorCorrespondenceLog
        fields = ('id', 'author_submitted_url', 'author_feedback', 'publication_title', 'contact_author_name')


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serialize users.
    """

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'username', 'email')


class NoteSerializer(serializers.ModelSerializer):
    added_by = serializers.StringRelatedField(read_only=True)
    date_added = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    deleted_on = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    deleted_by = serializers.StringRelatedField(read_only=True)
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Note
        fields = ('id', 'text', 'publication', 'added_by', 'date_added', 'deleted_on', 'deleted_by', 'is_deleted')


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = read_only_fields = ('id', 'audit_command_id', 'action', 'row_id', 'table', 'payload')


class AuditCommandSerializer(serializers.ModelSerializer):
    creator = serializers.StringRelatedField(read_only=True)
    auditlogs = AuditLogSerializer(many=True, read_only=True)

    class Meta:
        model = AuditCommand
        fields = read_only_fields = ('id', 'action', 'creator', 'date_added', 'message', 'auditlogs')


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }
        fields = read_only_fields = ('id', 'name', 'date_modified', 'date_added',)


class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }
        fields = ('id', 'name',)
        read_only_fields = ('id',)


class SponsorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sponsor
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }
        fields = ('id', 'name',)
        read_only_fields = ('id',)


class ModelDocumentationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelDocumentation
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }
        fields = ('id', 'name',)
        read_only_fields = ('id',)


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Container
        fields = '__all__'


class CreatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = ('id', 'given_name', 'family_name', 'type', 'email')
        read_only_fields = ('id',)


class PublicationAuditCommand:
    def __init__(self, id, creator, action, auditlogs, date_added):
        self.id = id
        self.creator = creator
        self.action = action
        self.auditlogs = auditlogs
        self.date_added = date_added

    def __lt__(self, other):
        return self.date_added > other.date_added

    @staticmethod
    def partition_by_audit_command_id(auditlogs):
        partioned_auditlogs = defaultdict(lambda: [])
        for auditlog in auditlogs:
            partioned_auditlogs[auditlog.audit_command_id].append(auditlog)
        return partioned_auditlogs

    @classmethod
    def many_from_queryset(cls, auditlogs):
        partioned_auditlogs = cls.partition_by_audit_command_id(auditlogs)
        audit_command_ids = partioned_auditlogs.keys()
        in_bulk_audit_commands = AuditCommand.objects.select_related('creator').in_bulk(audit_command_ids)

        publications_audit_commands = []
        for id, audit_command in in_bulk_audit_commands.items():
            auditlogs = partioned_auditlogs[id]
            publication_audit_command = cls(id=id, creator=audit_command.creator.username,
                                            action=audit_command.action, auditlogs=auditlogs,
                                            date_added=audit_command.date_added)
            publications_audit_commands.append(publication_audit_command)

        publications_audit_commands.sort()
        return publications_audit_commands


def publication_audit_command_serializer(auditlogs):
    partioned_auditlogs = defaultdict(lambda: [])
    for auditlog in auditlogs:
        partioned_auditlogs[auditlog.audit_command_id].append(auditlog)

    audit_command_ids = partioned_auditlogs.keys()
    in_bulk_audit_commands = AuditCommand.objects.select_related('creator').in_bulk(audit_command_ids)

    publications_audit_commands = []
    for id, audit_command in in_bulk_audit_commands.items():
        auditlogs = partioned_auditlogs[id]
        publication_audit_command = dict(id=id, creator=audit_command.creator.username,
                                         action=audit_command.action, auditlogs=auditlogs,
                                         date_added=audit_command.date_added)
        publications_audit_commands.append(publication_audit_command)

    return publications_audit_commands


class PublicationAuditCommandSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    creator = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    auditlogs = AuditLogSerializer(many=True)
    date_added = serializers.DateTimeField(read_only=True, format='%Y/%m/%d %H:%M')


class AuditCommandContibutionSerializer(serializers.Serializer):
    creator = serializers.StringRelatedField(read_only=True)
    contribution = serializers.FloatField(read_only=True)
    date_added = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')


class PublicationListSerializer(serializers.ModelSerializer):
    detail_url = serializers.CharField(source='get_absolute_url', read_only=True)
    date_modified = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    apa_citation_string = serializers.ReadOnlyField()
    contributor_data = AuditCommandContibutionSerializer(many=True, read_only=True)

    class Meta:
        model = Publication
        fields = (
            'apa_citation_string', 'date_modified', 'detail_url', 'contributor_data',
        )


class CodeArchiveUrlSerializer(serializers.ModelSerializer):
    id = serializers.ModelField(model_field=CodeArchiveUrl()._meta.get_field('id'), allow_null=True)
    creator = serializers.PrimaryKeyRelatedField(allow_null=True, queryset=User.objects.all())
    publication = serializers.PrimaryKeyRelatedField(allow_null=True, queryset=Publication.api.primary(),
                                                     required=False)
    category_name = serializers.CharField(read_only=True)

    class Meta:
        model = CodeArchiveUrl
        fields = (
            'id', 'category', 'category_name', 'system_overridable_category', 'url', 'status', 'creator', 'publication'
        )


class PublicationSerializer(serializers.ModelSerializer):
    """
    Serializes publication querysets.
    """
    detail_url = serializers.CharField(source='get_absolute_url', read_only=True)
    assigned_curator = serializers.StringRelatedField()
    code_archive_urls = CodeArchiveUrlSerializer(many=True)
    date_modified = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    notes = NoteSerializer(source='note_set', many=True, read_only=True)
    activity_logs = serializers.SerializerMethodField()
    tags = TagSerializer(many=True, read_only=True)
    platforms = PlatformSerializer(many=True)
    sponsors = SponsorSerializer(many=True)
    container = ContainerSerializer(read_only=True)
    model_documentation = ModelDocumentationSerializer(many=True)
    creators = CreatorSerializer(many=True, read_only=True)
    status_options = serializers.SerializerMethodField()
    code_archive_category_options = serializers.SerializerMethodField()
    code_archive_status_options = serializers.SerializerMethodField()
    apa_citation_string = serializers.ReadOnlyField()
    flagged = serializers.BooleanField()

    """
    XXX: copy-pasted from default ModelSerializer code but omitting the raise_errors_on_nested_writes. Revisit at some
    point. See http://www.django-rest-framework.org/api-guide/serializers/#writable-nested-representations for more
    details
    """

    def get_queryset(self):
        return Publication.objects.filter(is_primary=True)

    def get_activity_logs(self, obj):
        audit_logs = AuditLog.objects \
            .filter(Q(table=obj._meta.model_name, row_id=obj.id) |
                    Q(payload__data__publication_id=obj.id))
        pacs = PublicationAuditCommand.many_from_queryset(audit_logs)
        serialized_pacs = [PublicationAuditCommandSerializer(pac).data for pac in pacs]
        return serialized_pacs

    def get_code_archive_category_options(self, obj):
        return [{'value': choice.id,
                 'label': f'{choice.category} / {choice.subcategory}' if choice.subcategory else choice.category}
                for choice in CodeArchiveUrlCategory.objects.all()]

    def get_code_archive_status_options(self, obj):
        return [{'value': choice[0], 'label': str(choice[1])} for choice in CodeArchiveUrl.STATUS]

    def get_status_options(self, obj):
        return {choice[0]: str(choice[1]) for choice in Publication.Status}

    @staticmethod
    def save_model_documentation(audit_command, publication, raw_model_documentations):
        names = [model_documentation_raw['name'] for model_documentation_raw in raw_model_documentations]
        for name in names:
            model_documentation = ModelDocumentation.objects.get(name=name)
            PublicationModelDocumentations.objects.log_get_or_create(audit_command=audit_command,
                                                                     publication=publication,
                                                                     publication_id=publication.id,
                                                                     model_documentation_id=model_documentation.id)
        PublicationModelDocumentations.objects \
            .exclude(model_documentation__in=ModelDocumentation.objects.filter(name__in=names)) \
            .filter(publication=publication) \
            .log_delete(audit_command=audit_command)

    @staticmethod
    def save_platform(audit_command, publication, raw_platforms):
        names = [raw_platform['name'] for raw_platform in raw_platforms]
        for name in names:
            platform, created = Platform.objects.log_get_or_create(audit_command=audit_command, publication=publication,
                                                                   name=name)
            PublicationPlatforms.objects.log_get_or_create(audit_command=audit_command,
                                                           publication=publication,
                                                           publication_id=publication.id,
                                                           platform_id=platform.id)
        PublicationPlatforms.objects \
            .exclude(platform__in=Platform.objects.filter(name__in=names)) \
            .filter(publication=publication) \
            .log_delete(audit_command=audit_command)

    @staticmethod
    def save_sponsor(audit_command, publication, raw_sponsors):
        names = [raw_sponsor['name'] for raw_sponsor in raw_sponsors]
        for name in names:
            platform, created = Sponsor.objects.log_get_or_create(audit_command=audit_command, publication=publication,
                                                                  name=name)
            PublicationSponsors.objects.log_get_or_create(audit_command=audit_command,
                                                          publication=publication,
                                                          publication_id=publication.id,
                                                          sponsor_id=platform.id)
        PublicationSponsors.objects \
            .exclude(sponsor__in=Sponsor.objects.filter(name__in=names)) \
            .filter(publication=publication) \
            .log_delete(audit_command=audit_command)

    @staticmethod
    def save_code_archive_url(audit_command, publication, raw_code_archive_urls):
        code_archive_urls = []
        for raw_code_archive_url in raw_code_archive_urls:
            logger.info(pformat(raw_code_archive_url))
            pk = raw_code_archive_url.get('id')
            if pk is not None:
                code_archive_url = CodeArchiveUrl.objects.get(pk=pk)
                code_archive_url.log_update(audit_command=audit_command,
                                            system_overridable_category=raw_code_archive_url[
                                                'system_overridable_category'],
                                            category=raw_code_archive_url['category'],
                                            status=raw_code_archive_url['status'],
                                            url=raw_code_archive_url['url'])
            else:
                code_archive_url = CodeArchiveUrl.objects.log_create(audit_command=audit_command,
                                                                     creator=audit_command.creator,
                                                                     publication=publication,
                                                                     publication_id=publication.id,
                                                                     system_overridable_category=raw_code_archive_url[
                                                                         'system_overridable_category'],
                                                                     category=raw_code_archive_url['category'],
                                                                     status=raw_code_archive_url['status'],
                                                                     url=raw_code_archive_url['url'])
            code_archive_urls.append(code_archive_url.id)

        CodeArchiveUrl.objects \
            .exclude(id__in=code_archive_urls) \
            .filter(publication=publication) \
            .log_delete(audit_command=audit_command)

    @classmethod
    def save_related(cls, audit_command, publication, validated_data):
        cls.save_model_documentation(audit_command=audit_command,
                                     publication=publication,
                                     raw_model_documentations=validated_data['model_documentation'])
        cls.save_platform(audit_command=audit_command,
                          publication=publication,
                          raw_platforms=validated_data['platforms'])
        cls.save_sponsor(audit_command=audit_command,
                         publication=publication,
                         raw_sponsors=validated_data['sponsors'])
        cls.save_code_archive_url(audit_command=audit_command,
                                  publication=publication,
                                  raw_code_archive_urls=validated_data['code_archive_urls'])

    def create(self, audit_command, validated_data):
        ModelClass = self.Meta.model

        # Remove many-to-many relationships from validated_data.
        # They are not valid arguments to the default `.create()` method,
        # as they require that the instance has already been saved.
        info = model_meta.get_field_info(ModelClass)
        many_to_many = {}
        for field_name, relation_info in info.relations.items():
            if relation_info.to_many and (field_name in validated_data):
                many_to_many[field_name] = validated_data.pop(field_name)

        instance = ModelClass.objects.log_create(audit_command=audit_command, **validated_data)

        # Save many-to-many relationships after the instance is created.
        self.save_related(audit_command=audit_command,
                          publication=instance,
                          validated_data=validated_data)

        return instance

    def update(self, audit_command, instance, validated_data):
        concrete_changes = {}

        raw_model_documentations = validated_data.pop('model_documentation')
        self.save_model_documentation(audit_command=audit_command, publication=instance,
                                      raw_model_documentations=raw_model_documentations)

        raw_platforms = validated_data.pop('platforms')
        self.save_platform(audit_command=audit_command, publication=instance, raw_platforms=raw_platforms)

        raw_sponsors = validated_data.pop('sponsors')
        self.save_sponsor(audit_command=audit_command, publication=instance, raw_sponsors=raw_sponsors)

        raw_code_archive_urls = validated_data.pop('code_archive_urls')
        self.save_code_archive_url(audit_command=audit_command, publication=instance,
                                   raw_code_archive_urls=raw_code_archive_urls)

        for field_name, updated_data_value in validated_data.items():
            try:
                current_data_value = getattr(instance, field_name)
            except AttributeError:
                raise ValidationError("'{0}' not a field of publication with id={1} and title={2}".format(
                    field_name, instance.id, instance.title))

            if updated_data_value != current_data_value:
                concrete_changes[field_name] = updated_data_value

        if concrete_changes:
            instance.log_update(audit_command=audit_command, **concrete_changes)

        return instance

    def save(self, user, **kwargs):
        # FIXME: brittle, reliant on rest_framework.serializers internals
        # Modified from rest_framework/serializers method
        audit_command = AuditCommand.objects.create(creator=user,
                                                    action=AuditCommand.Action.MANUAL)

        assert not hasattr(self, 'save_object'), (
            'Serializer `%s.%s` has old-style version 2 `.save_object()` '
            'that is no longer compatible with REST framework 3. '
            'Use the new-style `.create()` and `.update()` methods instead.' %
            (self.__class__.__module__, self.__class__.__name__)
        )

        assert hasattr(self, '_errors'), (
            'You must call `.is_valid()` before calling `.save()`.'
        )

        assert not self.errors, (
            'You cannot call `.save()` on a serializer with invalid data.'
        )

        # Guard against incorrect use of `serializer.save(commit=False)`
        assert 'commit' not in kwargs, (
            "'commit' is not a valid keyword argument to the 'save()' method. "
            "If you need to access data before committing to the database then "
            "inspect 'serializer.validated_data' instead. "
            "You can also pass additional keyword arguments to 'save()' if you "
            "need to set extra attributes on the saved model instance. "
            "For example: 'serializer.save(owner=request.user)'.'"
        )

        assert not hasattr(self, '_data'), (
            "You cannot call `.save()` after accessing `serializer.data`."
            "If you need to access data before committing to the database then "
            "inspect 'serializer.validated_data' instead. "
        )

        validated_data = dict(
            list(self.validated_data.items()) +
            list(kwargs.items())
        )

        if self.instance is not None:
            self.instance = self.update(audit_command, self.instance, validated_data)
            assert self.instance is not None, (
                '`update()` did not return an object instance.'
            )
        else:
            self.instance = self.create(audit_command, validated_data)
            assert self.instance is not None, (
                '`create()` did not return an object instance.'
            )

        return self.instance

    @property
    def modified_data(self):
        return getattr(self, '_modified_data', defaultdict(tuple))

    @property
    def modified_data_text(self):
        # md_list = [u"{}: {} -> {}".format(key, pair[0], pair[1]) for key, pair in self.modified_data.items()]
        mdl = [u"{}: {} -> {}".format(key, pair[0], pair[1]) for key, pair in self.modified_data.items()]
        return u" | ".join(mdl)

    class Meta:
        model = Publication
        fields = (
            'id', 'apa_citation_string', 'activity_logs', 'assigned_curator', 'contact_author_name',
            'contact_email', 'container', 'creators', 'date_modified', 'detail_url', 'flagged', 'model_documentation',
            'notes', 'pages', 'platforms', 'sponsors', 'status', 'status_options', 'tags', 'title', 'volume',
            'year_published', 'doi', 'code_archive_urls', 'code_archive_status_options', 'code_archive_category_options'
        )


class PublicationMergeSerializer(serializers.Serializer):
    pass


class ContactFormSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField()
    message = serializers.CharField()

    security_hash = serializers.CharField()
    timestamp = serializers.CharField()
    # honeypot field
    contact_number = serializers.CharField(allow_blank=True)

    def validate_contact_number(self, value):
        if value:
            raise serializers.ValidationError("Honeypot bot alert failed.")
        return value

    def validate_timestamp(self, value):
        """ spam protection currently only accept form submissions between 3 seconds and 2 hours """
        min_seconds = 3
        max_seconds = 2 * 60 * 60
        difference = float(time.time()) - float(value)
        if not (min_seconds < difference < max_seconds):
            raise serializers.ValidationError("Timestamp check failed")
        return value

    def validate(self, data):
        security_hash = data['security_hash']
        timestamp = str(data['timestamp'])

        info = (timestamp, settings.SECRET_KEY)
        new_security_hash = sha1("".join(info).encode("ascii")).hexdigest()
        if security_hash == new_security_hash:
            return data
        logger.warn("timestamp was altered, flagging as invalid")
        raise serializers.ValidationError("timestamp was tampered.")

    def save(self):
        # name = self.validated_data['name']
        email = self.validated_data['email']
        message = self.validated_data['message']

        send_mail(from_email=email,
                  message=message,
                  subject="CoMSES Catalog Feedback",
                  recipient_list=[settings.DEFAULT_FROM_EMAIL])


class PublicationAggregationSerializer(serializers.Serializer):
    """
    Serializes the aggregated data for Journal, Platform, and Sponsors relation.
    name: String - representing name of the aggregated data i.e sponsors name, platforms name
    published_count - Integer - represent the total count of published paper for the given name
    code_availability_count - Integer -  represent the count of code availability for the published paper
    """
    name = serializers.ReadOnlyField()
    published_count = serializers.ReadOnlyField()
    code_availability_count = serializers.ReadOnlyField()


# Serializes the aggregated data for Author relation.
class AuthorAggregrationSerializer(serializers.Serializer):
    name = serializers.ReadOnlyField()
    given_name = serializers.ReadOnlyField()
    family_name = serializers.ReadOnlyField()
    published_count = serializers.ReadOnlyField()
    code_availability_count = serializers.ReadOnlyField()


class SuggestMergeInstanceSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class SuggestAuthorMergeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    family_name = serializers.CharField(allow_blank=False)
    given_name = serializers.CharField(allow_blank=False)
    orcid = serializers.CharField()


class SuggestOtherMergeSerializer(serializers.Serializer):
    name = serializers.CharField()


class SuggestMergeSerializer(serializers.Serializer):
    model_name = serializers.CharField()
    instances = SuggestMergeInstanceSerializer(many=True)
    new_content = serializers.JSONField()
    email = serializers.EmailField(required=False, min_length=5)

    def validate_instances(self, value):
        if len(value) < 2:
            raise serializers.ValidationError('must have multiple instances to merge')
        return value

    def validate_new_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('new_content must be a dict')
        return value

    def validate(self, data):
        raw_content = data['new_content']
        if data['model_name'] == 'author':
            serializer = SuggestAuthorMergeSerializer(data=raw_content)
            serializer.is_valid()
        else:
            serializer = SuggestOtherMergeSerializer(data=raw_content)
            serializer.is_valid()
        data['new_content'] = serializer.data
        return data
