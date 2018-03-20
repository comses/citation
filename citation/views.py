from citation.models import (Publication, InvitationEmail, Platform, Sponsor, Tag, Container, ModelDocumentation,
                             Note, URLStatusLog )
from citation.ping_urls import categorize_url
from citation.serializers import (CatalogPagination, ModelDocumentationSerializer, NoteSerializer,
                                  PublicationSerializer, PublicationListSerializer, )

from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Max
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, resolve_url

from json import dumps

import logging

from rest_framework.response import Response
from rest_framework import status, renderers, generics

logger = logging.getLogger(__name__)

SPONSORS_DEFAULT_FILTERS = ["United States National Science Foundation (NSF)"]
TAGS_DEFAULT_FILTERS = ["Dynamics", "Simulation"]

def generate_network_graph_group_by_sponsors(filter):
    publication = Publication.api.primary(status="REVIEWED").prefetch_related('sponsors', 'creators')
    nodes = []
    links = []
    tmp = []
    if 'sponsors__name__in' in filter:
        sponsors_filter = filter['sponsors__name__in']
    else :
        sponsors_filter = SPONSORS_DEFAULT_FILTERS
        filter['sponsors__name__in'] = sponsors_filter
    # fetching only filtered publication
    primary_publications = Publication.api.primary(status='REVIEWED', **filter)

    # fetches links that satisfies the given filter
    links_candidates = Publication.api.primary(status='REVIEWED', **filter,
                                               citations__in=primary_publications).values_list('pk', 'citations')

    # discarding rest keeping only nodes used in forming network link
    nodes_candidates = generate_node_candidates(links_candidates)

    # generates set of nodes for graph data and identify which group node belongs to
    # by mapping publication tags values with the user requested tags value
    # Appending additional info to the node(publication) i.e authors, title, tags
    for pub in nodes_candidates:
        sponsors = list(t[0] for t in publication.get(pk=pub).sponsors.all().values_list('name'))
        value = next((sponsor for sponsor in sponsors if sponsor in sponsors_filter), None)
        if value:
            tmp.append(pub)
            nodes.append({"name": pub, "group": value, 'tags': ','.join(
                ['{0}'.format(t.name) for t in
                 publication.get(pk=pub).tags.all()]), 'sponsors': sponsors, "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})
        else:
            tmp.append(pub)
            nodes.append({"name": pub, "group": "others", 'tags': ','.join(
                ['{0}'.format(t.name) for t in
                 publication.get(pk=pub).tags.all()]), 'sponsors': sponsors, "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})

    # Identifies link between two nodes and caching all connected node for generating collapsible tree structure
    for pub in links_candidates:
        links.append({"source": tmp.index(pub[0]), "target": tmp.index(pub[1]), "value": 1})

    sponsors_filter.append("others")
    return {"nodes": nodes, "links": links}, sponsors_filter


def generate_network_graph_group_by_tags(filter):
    publication = Publication.api.primary(status="REVIEWED").prefetch_related('tags', 'creators')
    nodes = []
    links = []
    tmp = []
    if 'tags__name__in' in filter:
        tags_filter = filter['tags__name__in']
    else:
        tags_filter = TAGS_DEFAULT_FILTERS
        filter['tags__name__in'] = tags_filter
    # fetching only filtered publication
    primary_publications = Publication.api.primary(status='REVIEWED', **filter)

    # fetches links that satisfies the given filter
    links_candidates = Publication.api.primary(status='REVIEWED', **filter,
                                               citations__in=primary_publications).values_list('pk', 'citations')

    # discarding rest keeping only nodes used in forming network link
    nodes_candidates = generate_node_candidates(links_candidates)
    # Forming network group by tags
    for pub in nodes_candidates:
        tags = list(t[0] for t in publication.get(pk=pub).tags.all().values_list('name'))
        value = next((tag for tag in tags if tag in tags_filter), None)
        if value:
            tmp.append(pub)
            nodes.append({"name": pub, "group": value, 'tags': tags, 'sponsors': ','.join(
                ['{0}'.format(s.name) for s in
                 publication.get(pk=pub).sponsors.all()]), "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})
        else:
            tmp.append(pub)
            nodes.append({"name": pub, "group": "others", 'tags': tags, 'sponsors': ','.join(
                ['{0}'.format(s.name) for s in
                 publication.get(pk=pub).sponsors.all()]), "Authors": ', '.join(
                ['{0}, {1}.'.format(c.family_name, c.given_name_initial) for c in
                 publication.get(pk=pub).creators.all()]),
                          "title": publication.filter(pk=pub).values_list('title')[0][0]})
    for pub in links_candidates:
        links.append(
            {"source": tmp.index(pub[0]), "target": tmp.index(pub[1]),
             "value": 1})
    tags_filter.append("others")
    return {"nodes": nodes, "links": links}, tags_filter


def generate_node_candidates(links_candidates):
    nodes = set()
    for pub in links_candidates:
        nodes.add(pub[1])
        nodes.add(pub[0])
    return nodes


def generate_publication_code_platform_data(filter, classifier, name):
    pubs = Publication.api.primary(status='REVIEWED', **filter)
    url_logs = URLStatusLog.objects.filter(publication__in=pubs).values('publication').order_by('publication', '-last_modified'). \
        annotate(last_modified=Max('last_modified')).values('publication', 'type').order_by('publication')

    platform_dct = {}
    availability = []
    non_availability = []
    years_list = []

    if url_logs:
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: url_logs.filter(type=platform_name[0]).count()})
    else:
        for platform_name in URLStatusLog.PLATFORM_TYPES:
            platform_dct.update({platform_name[0]: 0})
        for pub in pubs:
            if pub.code_archive_url is not '':
                platform_type = categorize_url(pub.code_archive_url)
                platform_dct.update({platform_type: platform_dct[platform_type] + 1})

    if pubs:
        for pub in pubs:
            if pub.year_published is not None and pub.code_archive_url is not '':
                availability.append(pub.year_published)
            else:
                non_availability.append(pub.year_published)
            years_list.append(pub.year_published)

        distribution_data = []
        for year in set(years_list):
            if year is not None:
                present = availability.count(year) * 100 / len(years_list)
                absent = non_availability.count(year) * 100 / len(years_list)
                total = present + absent
                distribution_data.append(
                    {'relation': classifier, 'name': name, 'date': year,
                     'Code Available': availability.count(year),
                     'Code Not Available': non_availability.count(year),
                     'Code Available Per': present * 100 / total,
                     'Code Not Available Per': absent * 100 / total})

        return distribution_data, [platform_dct]


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