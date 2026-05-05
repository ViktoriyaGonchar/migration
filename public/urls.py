from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("", views.seo_landing, name="seo"),
    path("app/", views.app_index, name="app"),
]
