from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "app": "cartrends-crm"})


urlpatterns = [
    path("health", health),
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("api/", include("crm.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("intake.urls")),
    path("api/", include("workspace.urls")),
    path("api/", include("webforms.urls")),
    path("api/", include("hr.urls")),
    path("api/", include("directory.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
