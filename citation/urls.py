from rest_framework import routers
from rest_framework.urlpatterns import format_suffix_patterns
from django.conf.urls import url
from django.views.generic import RedirectView, TemplateView

from . import views

app_name = 'citation'

# django rest framework endpoints that can generate JSON / HTML
urlpatterns = format_suffix_patterns([
    url(r'^publications/$', views.PublicationList.as_view(), name='publications'),
    url(r'^publication/(?P<pk>\d+)(?:/(?P<slug>[-\w\d]+))?/$', views.CuratorPublicationDetail.as_view(), name='publication_detail'),
    url(r'^notes/$', views.NoteList.as_view(), name='notes'),
    url(r'^note/(?P<pk>\d+)/$', views.NoteDetail.as_view(), name='note_detail'),
])