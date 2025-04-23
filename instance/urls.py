from django.contrib import admin
from django.urls import path

urlpatterns = [
    # path("test/", include("tests.app.urls")),
    path("admin/", admin.site.urls),
]
