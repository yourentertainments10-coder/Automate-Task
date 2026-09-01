from rest_framework.routers import DefaultRouter

from .views import MistakeCategoryViewSet, MistakeSettingsView, MistakeViewSet, SOPViewSet

router = DefaultRouter()
router.register("mistakes", MistakeViewSet, basename="mistakes")
router.register("mistake-categories", MistakeCategoryViewSet, basename="mistake-categories")
router.register("sops", SOPViewSet, basename="sops")
router.register("mistake-settings", MistakeSettingsView, basename="mistake-settings")

urlpatterns = router.urls
