from django.urls import path
from django.conf.urls import url
from rest_framework.urlpatterns import format_suffix_patterns

from . import views

app_name = 'citation'

# django rest framework endpoints that can generate JSON / HTML
urlpatterns = format_suffix_patterns([
    path('publications/', views.PublicationList.as_view(), name='publications'),
    path('publication/<int:pk>/<slug:slug>/', views.CuratorPublicationDetail.as_view(),
         name='publication_detail'),
    path('notes/', views.NoteList.as_view(), name='notes'),
    path('note/<int:pk>/', views.NoteDetail.as_view(), name='note_detail'),
    path('author/<uuid:uuid>/update/', views.AuthorUpdateView.as_view(), name='author_correspondence'),
])
