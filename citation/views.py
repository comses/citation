import logging
from datetime import datetime
from json import dumps

from .util import send_markdown_email
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from rest_framework import status, renderers, generics, views
from rest_framework.response import Response

from .models import Publication, ModelDocumentation, Note, AuthorCorrespondenceLog
from .serializers import (CatalogPagination, ModelDocumentationSerializer, NoteSerializer,
                          PublicationSerializer, PublicationListSerializer, AuthorCorrespondenceLogSerializer)

logger = logging.getLogger(__name__)


class AuthorUpdateView(views.APIView):

    renderer_classes = (renderers.TemplateHTMLRenderer,)
    template_name = 'publication/author-update.html'

    def get_object(self, uuid):
        return get_object_or_404(AuthorCorrespondenceLog, uuid=uuid)

    def get(self, request, uuid):
        acl = self.get_object(uuid)
        serializer = AuthorCorrespondenceLogSerializer(instance=acl)
        return Response({
            'serializer': serializer,
            'author_correspondence': acl
        })

    def post(self, request, uuid):
        acl = self.get_object(uuid)
        serializer = AuthorCorrespondenceLogSerializer(acl, data=request.data)
        if not serializer.is_valid():
            logger.debug("serializer failed validation: %s", serializer)
            return Response({
                'serializer': serializer,
                'author_correspondence': acl
            })
        updated_acl = serializer.save()
        send_markdown_email(
            subject=f'[comses.net] model author feedback {updated_acl.author_submitted_url}',
            to=[settings.DEFAULT_FROM_EMAIL],
            template_name='email/author-feedback.txt',
            context=dict(publication=updated_acl.publication,
                         author_correspondence_log=updated_acl),
        )
        messages.success(request,
                         'Your submission has been received. Thank you for updating your publication metadata!')
        return redirect('/')


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

    def get(self, request, pk, slug=None, format=None):
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
