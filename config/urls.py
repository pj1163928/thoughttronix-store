"""URL configuration for the ThoughtTronix Store.

Every URL is named and every app has a namespace (e.g. ``products:catalog``).
Public catalog URLs use slugs; back-office URLs use pks.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from django.views.static import serve


def serve_media(request, path):
    """Serve an uploaded file from ``MEDIA_ROOT``, read at request time.

    Looked up per request rather than bound when this module loads, so a
    test that points ``MEDIA_ROOT`` at a temporary folder is served from it.
    """
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("dashboard.urls")),
    path("", include("orders.urls")),
    path("", include("wishlist.urls")),
    path("", include("products.urls")),
    path(
        "safety/",
        TemplateView.as_view(template_name="pages/recall_notices.html"),
        name="recall_notices",
    ),
]

if settings.SERVE_MEDIA:
    urlpatterns.append(
        path(f"{settings.MEDIA_URL.lstrip('/')}<path:path>", serve_media, name="media")
    )
