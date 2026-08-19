from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views
from .dashboard import dashboard
from .task_views import (
    HolidayViewSet, TaskActivityViewSet, TaskCategoryViewSet,
    TaskChangeRequestViewSet, TaskSettingsView, TaskTemplateViewSet,
    TaskViewSet,
)

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="tasks")
router.register("task-categories", TaskCategoryViewSet, basename="task-categories")
router.register("task-change-requests", TaskChangeRequestViewSet, basename="task-change-requests")
router.register("task-settings", TaskSettingsView, basename="task-settings")
router.register("task-templates", TaskTemplateViewSet, basename="task-templates")
router.register("task-activities", TaskActivityViewSet, basename="task-activities")
router.register("holidays", HolidayViewSet, basename="holidays")
router.register("leads", views.LeadViewSet, basename="leads")
router.register("quotations", views.QuotationViewSet, basename="quotations")
router.register("assignment-rules", views.AssignmentRuleViewSet, basename="assignment-rules")

urlpatterns = [path("dashboard/", dashboard)] + router.urls
