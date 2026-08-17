from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import IntakeViewSet
from .webhook import whatsapp_webhook

router = DefaultRouter()
router.register("intake", IntakeViewSet, basename="intake")

urlpatterns = [
    path("webhooks/whatsapp", whatsapp_webhook),
] + router.urls
