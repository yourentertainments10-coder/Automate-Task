import csv

from django.http import HttpResponse
from rest_framework import serializers, status as http, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasCapability, has_capability
from crm.serializers import UserBriefSerializer

from . import services
from .models import Advance, PayrollRun, Payslip, RunStatus, SalaryStructure


def can_manage_payroll(user) -> bool:
    return has_capability(user, "hr.manage")


# ------------------------------------------------------------ serializers

class SalaryStructureSerializer(serializers.ModelSerializer):
    user_detail = UserBriefSerializer(source="user", read_only=True)

    class Meta:
        model = SalaryStructure
        fields = ["id", "user", "user_detail", "monthly_gross", "basic", "pf_percent",
                  "professional_tax", "other_deduction", "effective_from", "note", "created_at"]

    def validate_monthly_gross(self, value):
        if value <= 0:
            raise serializers.ValidationError("Monthly gross must be greater than zero.")
        return value

    def validate(self, attrs):
        basic = attrs.get("basic", getattr(self.instance, "basic", None))
        gross = attrs.get("monthly_gross", getattr(self.instance, "monthly_gross", None))
        if basic and gross and basic > gross:
            raise serializers.ValidationError({"basic": "Basic cannot be more than the monthly gross."})
        return attrs


class AdvanceSerializer(serializers.ModelSerializer):
    user_detail = UserBriefSerializer(source="user", read_only=True)

    class Meta:
        model = Advance
        fields = ["id", "user", "user_detail", "amount", "given_on", "reason",
                  "recovered", "created_at"]
        read_only_fields = ["recovered"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Advance must be greater than zero.")
        return value


class PayslipSerializer(serializers.ModelSerializer):
    user_detail = UserBriefSerializer(source="user", read_only=True)
    total_deductions = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    month = serializers.IntegerField(source="run.month", read_only=True)
    year = serializers.IntegerField(source="run.year", read_only=True)
    run_status = serializers.CharField(source="run.status", read_only=True)

    class Meta:
        model = Payslip
        fields = ["id", "run", "month", "year", "run_status", "user", "user_detail",
                  "monthly_gross", "working_days", "payable_days", "lwp_days",
                  "earned_gross", "pf", "professional_tax", "advance_deduction",
                  "other_deduction", "total_deductions", "net_payable", "breakdown", "note"]


class PayrollRunSerializer(serializers.ModelSerializer):
    payslip_count = serializers.IntegerField(source="payslips.count", read_only=True)
    created_by_detail = UserBriefSerializer(source="created_by", read_only=True)

    class Meta:
        model = PayrollRun
        fields = ["id", "year", "month", "status", "working_days", "total_net",
                  "payslip_count", "created_by_detail", "finalised_at", "created_at"]
        read_only_fields = ["status", "working_days", "total_net", "finalised_at"]

    def validate(self, attrs):
        month = attrs.get("month")
        if month is not None and not 1 <= month <= 12:
            raise serializers.ValidationError({"month": "Month must be between 1 and 12."})
        return attrs


# ----------------------------------------------------------------- views

class SalaryStructureViewSet(viewsets.ModelViewSet):
    """Salary is sensitive: HR/Admin see everyone, employees see only their own."""
    permission_classes = [IsAuthenticated]
    serializer_class = SalaryStructureSerializer
    pagination_class = None

    def get_queryset(self):
        qs = SalaryStructure.objects.select_related("user")
        if not can_manage_payroll(self.request.user):
            return qs.filter(user=self.request.user)
        if self.request.query_params.get("user"):
            qs = qs.filter(user_id=self.request.query_params["user"])
        return qs

    def _guard(self):
        if not can_manage_payroll(self.request.user):
            raise PermissionDenied("Only HR/Admin can manage salary structures.")

    def perform_create(self, serializer):
        self._guard()
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._guard()
        serializer.save()

    def perform_destroy(self, instance):
        self._guard()
        if Payslip.objects.filter(breakdown__structure_id=instance.pk).exists():
            raise ValidationError({"detail": "This salary has already been used in a payslip — "
                                             "add a new one with a later effective date instead."})
        instance.delete()


class AdvanceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AdvanceSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Advance.objects.select_related("user")
        if not can_manage_payroll(self.request.user):
            return qs.filter(user=self.request.user)
        p = self.request.query_params
        if p.get("user"):
            qs = qs.filter(user_id=p["user"])
        if p.get("pending") == "true":
            qs = qs.filter(recovered=False)
        return qs

    def _guard(self):
        if not can_manage_payroll(self.request.user):
            raise PermissionDenied("Only HR/Admin can record advances.")

    def perform_create(self, serializer):
        self._guard()
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._guard()
        if serializer.instance.recovered:
            raise ValidationError({"detail": "A recovered advance cannot be edited."})
        serializer.save()

    def perform_destroy(self, instance):
        self._guard()
        if instance.recovered:
            raise ValidationError({"detail": "A recovered advance cannot be deleted."})
        instance.delete()


class PayrollRunViewSet(viewsets.ModelViewSet):
    permission_classes = [HasCapability.of("hr.manage")]
    serializer_class = PayrollRunSerializer
    queryset = PayrollRun.objects.select_related("created_by").all()
    pagination_class = None

    def perform_create(self, serializer):
        run = serializer.save(created_by=self.request.user)
        services.generate_run(run, User.objects.filter(is_active=True))

    def perform_destroy(self, instance):
        if instance.status == RunStatus.FINALISED:
            raise ValidationError({"detail": "A finalised payroll cannot be deleted."})
        instance.delete()

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        """Recalculate a draft run — safe to press after fixing attendance."""
        run = self.get_object()
        try:
            result = services.generate_run(run, User.objects.filter(is_active=True))
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        run.refresh_from_db()
        return Response({**result, "run": PayrollRunSerializer(run).data})

    @action(detail=True, methods=["post"])
    def finalise(self, request, pk=None):
        run = self.get_object()
        try:
            result = services.finalise(run)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        run.refresh_from_db()
        return Response({**result, "run": PayrollRunSerializer(run).data})

    @action(detail=True, methods=["get"])
    def payslips(self, request, pk=None):
        run = self.get_object()
        slips = run.payslips.select_related("user", "run")
        return Response(PayslipSerializer(slips, many=True).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        run = self.get_object()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="payroll-{run.year}-{run.month:02d}.csv"')
        writer = csv.writer(response)
        writer.writerow(["Employee", "Username", "Monthly gross", "Working days",
                         "Payable days", "LWP days", "Earned gross", "PF",
                         "Professional tax", "Advance", "Other deduction", "Net payable"])
        for s in run.payslips.select_related("user"):
            writer.writerow([
                s.user.get_full_name() or s.user.username, s.user.username,
                s.monthly_gross, s.working_days, s.payable_days, s.lwp_days,
                s.earned_gross, s.pf, s.professional_tax, s.advance_deduction,
                s.other_deduction, s.net_payable,
            ])
        writer.writerow([])
        writer.writerow(["", "", "", "", "", "", "", "", "", "", "TOTAL", run.total_net])
        return response


class PayslipViewSet(viewsets.ReadOnlyModelViewSet):
    """Employees can read their own payslips — only from finalised runs, so
    nobody sees a half-computed draft figure."""
    permission_classes = [IsAuthenticated]
    serializer_class = PayslipSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Payslip.objects.select_related("user", "run")
        if can_manage_payroll(self.request.user):
            p = self.request.query_params
            if p.get("user"):
                qs = qs.filter(user_id=p["user"])
            return qs
        return qs.filter(user=self.request.user, run__status=RunStatus.FINALISED)
