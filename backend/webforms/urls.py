from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("forms", views.FormViewSet, basename="forms")
router.register("form-fields", views.FormFieldViewSet, basename="form-fields")

urlpatterns = [
    path("public/forms/<str:token>/", views.public_form),
    path("public/forms/<str:token>/submit/", views.public_submit),
] + router.urls
