from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("salary-structures", views.SalaryStructureViewSet, basename="salary-structures")
router.register("advances", views.AdvanceViewSet, basename="advances")
router.register("payroll-runs", views.PayrollRunViewSet, basename="payroll-runs")
router.register("payslips", views.PayslipViewSet, basename="payslips")

urlpatterns = router.urls
