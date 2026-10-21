from django.urls import path

from attendance.api import api

urlpatterns = [path("", api.urls)]
