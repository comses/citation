import logging
from datetime import datetime
from json import dumps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import status, renderers, generics
from rest_framework.response import Response

from .models import Publication, ModelDocumentation, Note
from .serializers import (CatalogPagination, ModelDocumentationSerializer, NoteSerializer,
                          PublicationSerializer, PublicationListSerializer, )

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
        serializer = PublicationListSerializer(result_page, many=True)
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
            self.update_contribution_data(pk)
            serializer.save(user=request.user)
            return Response(serializer.data)
        logger.warning("serializer failed validation: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def update_contribution_data(pk):
        Publication.objects.get(pk=pk).contributor_data()


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
