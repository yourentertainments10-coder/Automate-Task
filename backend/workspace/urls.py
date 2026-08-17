from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("groups", views.GroupViewSet, basename="groups")
router.register("notices", views.NoticeViewSet, basename="notices")
router.register("link-collections", views.LinkCollectionViewSet, basename="link-collections")
router.register("links", views.LinkViewSet, basename="links")
router.register("ideas", views.IdeaViewSet, basename="ideas")

urlpatterns = router.urls
