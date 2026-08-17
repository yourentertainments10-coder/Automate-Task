from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("attendance", views.AttendanceViewSet, basename="attendance")
router.register("attendance-corrections", views.CorrectionViewSet, basename="attendance-corrections")
router.register("leave-types", views.LeaveTypeViewSet, basename="leave-types")
router.register("leaves", views.LeaveRequestViewSet, basename="leaves")
router.register("office-locations", views.OfficeLocationViewSet, basename="office-locations")

urlpatterns = [
    path("hr/config/", views.hr_config),
    path("hr/face/<int:user_id>/", views.face_enrolment),
] + router.urls
