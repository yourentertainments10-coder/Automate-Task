from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views
from .serializers import FlexibleLoginSerializer

router = DefaultRouter()
router.register("users", views.UserViewSet, basename="users")

urlpatterns = [
    path("auth/login", TokenObtainPairView.as_view(serializer_class=FlexibleLoginSerializer)),
    path("auth/refresh", TokenRefreshView.as_view()),
    path("auth/logout", views.logout),
    path("auth/me", views.me),
    path("auth/change-password", views.change_password),
    path("team/", views.team_directory),
    path("", include(router.urls)),
]
