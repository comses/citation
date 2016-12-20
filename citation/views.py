from citation.models import (Publication, InvitationEmail, Platform, Sponsor, Tag, Container, ModelDocumentation,
                             Note, )
from citation.forms import CatalogSearchForm
from citation.serializers import CatalogPagination, ModelDocumentationSerializer, NoteSerializer, PublicationSerializer, \
    UserProfileSerializer

from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, resolve_url

from haystack.generic_views import SearchView
from haystack.query import SearchQuerySet

from json import dumps

import logging

from rest_framework.response import Response
from rest_framework import status, renderers, generics

logger = logging.getLogger(__name__)


# Rest Framework Views
class PublicationList(LoginRequiredMixin, generics.GenericAPIView):
    """
    List all publications, or create a new publication
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
    # FIXME: look into properly implementing pagination via django rest framework
    pagination_class = CatalogPagination

    def get(self, request, format=None):
        publication_list = Publication.objects.all()
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(publication_list, request)
        serializer = PublicationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        return Response({'json': dumps(response)}, template_name="publication/list.html")

    def post(self, request, format=None):
        # adding current user to added_by field
        request.data.update({'added_by': request.user.id})
        # FIXME: hard coded PublicationSerializer should instead depend on incoming data
        serializer = PublicationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CuratorPublicationDetail(LoginRequiredMixin, generics.GenericAPIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get_object(self, pk):
        return get_object_or_404(Publication, pk=pk)

    def get(self, request, pk, slug, format=None):
        publication = self.get_object(pk)
        obj_url = publication.get_absolute_url()

        if self.request.path != obj_url:
            return HttpResponseRedirect(obj_url)

        serializer = PublicationSerializer(publication)
        model_documentation_serializer = ModelDocumentationSerializer(ModelDocumentation.objects.all(), many=True)
        return Response({'json': dumps(serializer.data), 'pk': pk,
                         'model_documentation_categories_json': dumps(ModelDocumentation.CATEGORIES),
                         'model_documentation_list_json': dumps(model_documentation_serializer.data)},
                        template_name='workflow/curator_publication_detail.html')

    def put(self, request, pk, slug=None):
        publication = self.get_object(pk)
        # FIXME: need to revisit this if we ever have other Publication Types - Books or Book Chapters may also refer to
        # computational models.
        serializer = PublicationSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data)
        logger.warning("serializer failed validation: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NoteDetail(LoginRequiredMixin, generics.GenericAPIView):
    """
    Retrieve, update or delete a note instance.
    """
    renderer_classes = (renderers.JSONRenderer,)

    def get_object(self, pk):
        return get_object_or_404(Note, pk=pk)

    def get(self, request, pk, format=None):
        note = self.get_object(pk)
        serializer = NoteSerializer(note)
        return Response({'json': dumps(serializer.data)})

    def put(self, request, pk):
        note = self.get_object(pk)
        serializer = NoteSerializer(note, data=request.data)
        logger.debug("serializer: %s", serializer)
        if serializer.is_valid():
            serializer.save(added_by=request.user)
            return Response(serializer.data)
        logger.error("serializer errors: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        note = self.get_object(pk)
        note.deleted_by = request.user
        note.deleted_on = datetime.today()
        note.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NoteList(LoginRequiredMixin, generics.GenericAPIView):
    """
    Get all the notes or create a note
    """
    renderer_classes = (renderers.JSONRenderer,)
    serializer_class = NoteSerializer

    def get(self, request, format=None):
        note = Note.objects.all()
        serializer = NoteSerializer(note, many=True)
        return Response({'json': dumps(serializer.data)})

    def post(self, request):
        # adding current user to added_by field
        serializer = NoteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(added_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Other Views
class AutocompleteView(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.JSONRenderer,)

    def get(self, request, format=None):
        query = request.GET.get('q', '').strip()
        sqs = SearchQuerySet().models(self.model_class)
        if query:
            sqs = sqs.autocomplete(name=query)
        data = [{'id': int(result.pk), 'name': result.name} for result in sqs]
        return Response(dumps(data))


class PlatformSearchView(AutocompleteView):
    @property
    def model_class(self):
        return Platform


class SponsorSearchView(AutocompleteView):
    @property
    def model_class(self):
        return Sponsor


class TagSearchView(AutocompleteView):
    @property
    def model_class(self):
        return Tag


class ModelDocumentationSearchView(AutocompleteView):
    @property
    def model_class(self):
        return ModelDocumentation


class JournalSearchView(AutocompleteView):
    @property
    def model_class(self):
        return Container


class CatalogSearchView(LoginRequiredMixin, SearchView):
    """ generic django haystack SearchView using a custom form """
    form_class = CatalogSearchForm


class CuratorWorkflowView(LoginRequiredMixin, SearchView):
    """ django haystack searchview """
    template_name = 'workflow/curator.html'
    form_class = CatalogSearchForm

    def get_context_data(self, **kwargs):
        context = super(CuratorWorkflowView, self).get_context_data(**kwargs)
        sqs = SearchQuerySet().filter(assigned_curator=self.request.user, is_primary=True).facet('status')
        context.update(facets=sqs.facet_counts(),
                       total_number_of_records=Publication.objects.filter(assigned_curator=self.request.user).count())
        return context

    def get_queryset(self):
        sqs = super(CuratorWorkflowView, self).get_queryset()
        return sqs.filter(assigned_curator=self.request.user, is_primary=True).order_by('-last_modified', '-status')
