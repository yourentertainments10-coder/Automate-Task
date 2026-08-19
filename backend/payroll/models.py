"""Payroll: salary structures, advances, and monthly runs computed from
the attendance the HR module already records.

Deliberately simple and Indian-small-business shaped: a monthly gross,
optional PF / professional tax / fixed deductions, and advances recovered
from the next payslip. Everything is derived from Attendance so payroll
and attendance can never disagree.
"""
from django.conf import settings
from django.db import models


class SalaryStructure(models.Model):
    """What an employee is paid, effective from a date. Keeping history
    means an old payslip can still be explained months later."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="salary_structures")
    monthly_gross = models.DecimalField(max_digits=10, decimal_places=2)
    basic = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                help_text="Optional. PF is computed on this when set, else on gross.")
    pf_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                     help_text="Employee PF share, e.g. 12.00. 0 = no PF.")
    professional_tax = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    effective_from = models.DateField()
    note = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "effective_from"],
                                    name="uniq_salary_effective_date"),
        ]

    def __str__(self):
        return f"{self.user} ₹{self.monthly_gross}/month from {self.effective_from}"


class Advance(models.Model):
    """Money paid to an employee ahead of payday, recovered from a payslip."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="advances")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    given_on = models.DateField()
    reason = models.CharField(max_length=200, blank=True, default="")
    recovered = models.BooleanField(default=False)
    recovered_in = models.ForeignKey("payroll.Payslip", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="recovered_advances")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-given_on", "-id"]


class RunStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    FINALISED = "finalised", "Finalised"


class PayrollRun(models.Model):
    """One month's payroll. Draft can be recalculated as many times as you
    like; finalising locks it and marks the advances recovered."""
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=RunStatus.choices, default=RunStatus.DRAFT)
    working_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    total_net = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    finalised_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="uniq_payroll_month"),
        ]

    def __str__(self):
        return f"Payroll {self.month:02d}/{self.year} [{self.status}]"


class Payslip(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="payslips")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="payslips")
    monthly_gross = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    working_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    payable_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    lwp_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    earned_gross = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pf = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    professional_tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    advance_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_payable = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Day-count breakdown so a payslip can be explained line by line
    breakdown = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["user__first_name", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["run", "user"], name="uniq_payslip_per_run"),
        ]

    @property
    def total_deductions(self):
        return self.pf + self.professional_tax + self.advance_deduction + self.other_deduction

    def __str__(self):
        return f"{self.user} {self.run.month:02d}/{self.run.year} ₹{self.net_payable}"
