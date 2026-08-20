from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve as _serve


def health(_request):
    return JsonResponse({"status": "ok", "app": "cartrends-crm"})


def spa(request, *_args, **_kwargs):
    """Catch-all for the React app's client-side routes (/tasks, /leads…) —
    a hard refresh on any of them must still load index.html."""
    index = settings.FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(open(index, "rb"), content_type="text/html")
    raise Http404("Frontend build not found — run `npm run build` in frontend/.")


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
    path("api/", include("payroll.urls")),
    path("api/", include("mistakes.urls")),
    # uploaded files (works in dev and on Render; Render's disk is ephemeral)
    re_path(r"^media/(?P<path>.*)$", _serve, {"document_root": settings.MEDIA_ROOT}),
    # everything else that isn't API/admin/static -> the React app
    re_path(r"^(?!api/|admin/|static/|media/|health).*$", spa),
]
