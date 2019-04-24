from django import forms
from django.contrib import admin
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.models import User
from django.db.models import OuterRef, Exists
from django.utils.translation import ugettext_lazy as _

from .models import (Author, AuditCommand, CodeArchiveUrl, Container,
                     ModelDocumentation, Note,
                     Platform, Publication,
                     Sponsor, SuggestedMerge, Tag)


class PublicationStatusListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = _('status')
    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return (tuple([(s[0], s[0]) for s in Publication.Status]))

    def queryset(self, request, queryset):
        if self.value() in Publication.Status:
            return queryset.filter(status=self.value())
        else:
            return queryset.all()


def assign_curator(modeladmin, request, queryset):
    assigned_curator_id = request.POST['assigned_curator_id']

    user = request.user
    audit_command = AuditCommand(creator=user, action=AuditCommand.Action.MANUAL)

    # Does not seem to be a Haystack method to update records based on a queryset so records are updated one at a time
    # to keep the Solr index in sync
    for publication in queryset:
        publication.log_update(audit_command=audit_command, assigned_curator_id=assigned_curator_id)


assign_curator.short_description = 'Assign Curator to Publications'


class PublicationCuratorForm(ActionForm):
    assigned_curator_id = forms.ModelChoiceField(queryset=User.objects.filter(is_active=True), label='User Name')


class PublicationAdmin(admin.ModelAdmin):
    list_filter = ('assigned_curator', 'is_primary', PublicationStatusListFilter)
    action_form = PublicationCuratorForm
    actions = [assign_curator]


class ManyRelatedFilterMixin:
    publication_related_field = None

    def get_queryset(self, request=None):
        publications = Publication.api \
            .primary() \
            .reviewed() \
            .filter(**{self.publication_related_field: OuterRef('pk')})
        return self.model.objects.annotate(has_pubs=Exists(publications)).filter(has_pubs=True)


class AuthorAdmin(ManyRelatedFilterMixin, admin.ModelAdmin):
    publication_related_field = 'creators'


class PlatformAdmin(ManyRelatedFilterMixin, admin.ModelAdmin):
    publication_related_field = 'platforms'


class SponsorAdmin(ManyRelatedFilterMixin, admin.ModelAdmin):
    publication_related_field = 'sponsors'


class TagAdmin(ManyRelatedFilterMixin, admin.ModelAdmin):
    publication_related_field = 'tags'


def apply_suggested_merges(modeladmin, request, queryset):
    creator = request.user
    for suggested_merge in queryset:
        suggested_merge.merge(creator)


apply_suggested_merges.short_description = "Apply suggested merges"


class SuggestedMergeAdmin(admin.ModelAdmin):
    list_display = ['duplicate_text', 'content_type', 'new_content', 'creator', 'date_applied']
    list_filter = ['content_type', 'date_applied']
    actions = [apply_suggested_merges]


admin.site.register(Author, AuthorAdmin)
admin.site.register(Container)
admin.site.register(CodeArchiveUrl)
admin.site.register(ModelDocumentation)
admin.site.register(Note)
admin.site.register(Platform, PlatformAdmin)
admin.site.register(Publication)
admin.site.register(Sponsor, SponsorAdmin)
admin.site.register(SuggestedMerge, SuggestedMergeAdmin)
admin.site.register(Tag, TagAdmin)
