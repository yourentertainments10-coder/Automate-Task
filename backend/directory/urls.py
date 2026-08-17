from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("directory/industries", views.IndustryViewSet, basename="industries")
router.register("directory/templates", views.DirectoryTemplateViewSet, basename="directory-templates")

urlpatterns = router.urls
