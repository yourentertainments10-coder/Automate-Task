from django.contrib import admin

from .models import Advance, PayrollRun, Payslip, SalaryStructure


@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):
    list_display = ("user", "monthly_gross", "pf_percent", "effective_from")


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("year", "month", "status", "working_days", "total_net")
    list_filter = ("status", "year")


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ("user", "run", "payable_days", "earned_gross", "net_payable")


admin.site.register(Advance)
