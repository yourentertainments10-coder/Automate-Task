from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import Holiday
from hr.models import Attendance, LeaveRequest, LeaveType

from . import services
from .models import Advance, PayrollRun, Payslip, SalaryStructure

# September 2026: 30 days, Sundays fall on 6/13/20/27 -> 4 week-offs
YEAR, MONTH = 2026, 9


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


def mark(user, day, status="present"):
    return Attendance.objects.create(user=user, date=date(YEAR, MONTH, day), status=status)


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.hr = make("neha", Role.HR_MANAGER, "hr")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        SalaryStructure.objects.create(user=self.rahul, monthly_gross=Decimal("26000"),
                                       effective_from=date(2026, 1, 1))

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def run_payroll(self):
        run = PayrollRun.objects.create(year=YEAR, month=MONTH)
        services.generate_run(run, User.objects.filter(is_active=True))
        run.refresh_from_db()
        return run


class CalculationTests(Base):
    def test_working_days_excludes_sundays_and_holidays(self):
        self.assertEqual(services.working_days_in(YEAR, MONTH), Decimal(26))
        Holiday.objects.create(name="Ganesh Chaturthi", date=date(YEAR, MONTH, 14))
        self.assertEqual(services.working_days_in(YEAR, MONTH), Decimal(25))

    def test_full_attendance_pays_full_salary(self):
        for day in range(1, 31):
            d = date(YEAR, MONTH, day)
            if d.weekday() != 6:
                mark(self.rahul, day)
        slip = self.run_payroll().payslips.get(user=self.rahul)
        self.assertEqual(slip.working_days, Decimal("26.0"))
        self.assertEqual(slip.payable_days, Decimal("26.0"))
        self.assertEqual(slip.lwp_days, Decimal("0.0"))
        self.assertEqual(slip.net_payable, Decimal("26000.00"))

    def test_absent_days_are_deducted(self):
        for day in range(1, 31):
            d = date(YEAR, MONTH, day)
            if d.weekday() != 6 and day > 2:      # 1st & 2nd absent (both weekdays)
                mark(self.rahul, day)
        slip = self.run_payroll().payslips.get(user=self.rahul)
        self.assertEqual(slip.payable_days, Decimal("24.0"))
        self.assertEqual(slip.lwp_days, Decimal("2.0"))
        self.assertEqual(slip.net_payable, Decimal("24000.00"))   # 26000/26 = 1000/day

    def test_half_day_counts_as_half(self):
        for day in range(1, 31):
            d = date(YEAR, MONTH, day)
            if d.weekday() != 6:
                mark(self.rahul, day, "half_day" if day == 1 else "present")
        slip = self.run_payroll().payslips.get(user=self.rahul)
        self.assertEqual(slip.payable_days, Decimal("25.5"))
        self.assertEqual(slip.net_payable, Decimal("25500.00"))

    def test_paid_leave_is_paid_unpaid_leave_is_not(self):
        paid = LeaveType.objects.create(name="Casual", annual_quota=12, paid=True)
        unpaid = LeaveType.objects.create(name="Unpaid", annual_quota=30, paid=False)
        LeaveRequest.objects.create(user=self.rahul, leave_type=paid, days=1, reason="x",
                                    status="approved", start_date=date(YEAR, MONTH, 1),
                                    end_date=date(YEAR, MONTH, 1))
        LeaveRequest.objects.create(user=self.rahul, leave_type=unpaid, days=1, reason="x",
                                    status="approved", start_date=date(YEAR, MONTH, 2),
                                    end_date=date(YEAR, MONTH, 2))
        for day in range(1, 31):
            d = date(YEAR, MONTH, day)
            if d.weekday() != 6:
                mark(self.rahul, day, "leave" if day in (1, 2) else "present")
        slip = self.run_payroll().payslips.get(user=self.rahul)
        self.assertEqual(slip.breakdown["paid_leave"], 1)
        self.assertEqual(slip.breakdown["unpaid_leave"], 1)
        self.assertEqual(slip.payable_days, Decimal("25.0"))      # 24 present + 1 paid leave
        self.assertEqual(slip.net_payable, Decimal("25000.00"))

    def test_pf_professional_tax_and_other_deductions(self):
        SalaryStructure.objects.create(
            user=self.manager, monthly_gross=Decimal("30000"), basic=Decimal("15000"),
            pf_percent=Decimal("12"), professional_tax=Decimal("200"),
            other_deduction=Decimal("300"), effective_from=date(2026, 1, 1))
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6:
                mark(self.manager, day)
        slip = self.run_payroll().payslips.get(user=self.manager)
        self.assertEqual(slip.earned_gross, Decimal("30000.00"))
        self.assertEqual(slip.pf, Decimal("1800.00"))            # 12% of basic
        self.assertEqual(slip.professional_tax, Decimal("200.00"))
        self.assertEqual(slip.total_deductions, Decimal("2300.00"))
        self.assertEqual(slip.net_payable, Decimal("27700.00"))

    def test_latest_effective_structure_wins(self):
        SalaryStructure.objects.create(user=self.rahul, monthly_gross=Decimal("32000"),
                                       effective_from=date(YEAR, MONTH, 1))
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6:
                mark(self.rahul, day)
        slip = self.run_payroll().payslips.get(user=self.rahul)
        self.assertEqual(slip.monthly_gross, Decimal("32000.00"))

    def test_no_attendance_pays_zero_and_never_goes_negative(self):
        """An employee with no attendance in the month earns nothing — and
        fixed deductions must not push the payslip below zero."""
        SalaryStructure.objects.create(
            user=self.manager, monthly_gross=Decimal("30000"), basic=Decimal("15000"),
            pf_percent=Decimal("12"), professional_tax=Decimal("200"),
            other_deduction=Decimal("300"), effective_from=date(2026, 1, 1))
        slip = self.run_payroll().payslips.get(user=self.manager)
        self.assertEqual(slip.payable_days, Decimal("0.0"))
        self.assertEqual(slip.earned_gross, Decimal("0.00"))
        self.assertEqual(slip.pf, Decimal("0.00"))
        self.assertEqual(slip.professional_tax, Decimal("0.00"))
        self.assertEqual(slip.other_deduction, Decimal("0.00"))
        self.assertEqual(slip.net_payable, Decimal("0.00"))

    def test_pf_is_prorated_on_earned_basic(self):
        SalaryStructure.objects.create(
            user=self.manager, monthly_gross=Decimal("26000"), basic=Decimal("13000"),
            pf_percent=Decimal("12"), effective_from=date(2026, 1, 1))
        worked = 0
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6 and worked < 13:
                mark(self.manager, day)
                worked += 1
        slip = self.run_payroll().payslips.get(user=self.manager)
        self.assertEqual(slip.payable_days, Decimal("13.0"))       # half the month
        self.assertEqual(slip.earned_gross, Decimal("13000.00"))
        self.assertEqual(slip.pf, Decimal("780.00"))               # 12% of HALF the basic
        self.assertEqual(slip.net_payable, Decimal("12220.00"))

    def test_employee_without_salary_is_skipped_not_zeroed(self):
        run = PayrollRun.objects.create(year=YEAR, month=MONTH)
        result = services.generate_run(run, User.objects.filter(is_active=True))
        self.assertEqual(result["payslips"], 1)                   # only rahul has a structure
        self.assertIn("neha", " ".join(result["skipped_no_salary"]))
        self.assertFalse(Payslip.objects.filter(user=self.hr).exists())


class AdvanceTests(Base):
    def setUp(self):
        super().setUp()
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6:
                mark(self.rahul, day)

    def test_advance_is_recovered_and_settled_on_finalise(self):
        Advance.objects.create(user=self.rahul, amount=Decimal("5000"),
                               given_on=date(YEAR, MONTH, 5), reason="Festival")
        run = self.run_payroll()
        slip = run.payslips.get(user=self.rahul)
        self.assertEqual(slip.advance_deduction, Decimal("5000.00"))
        self.assertEqual(slip.net_payable, Decimal("21000.00"))
        services.finalise(run)
        self.assertTrue(Advance.objects.get().recovered)

    def test_advance_never_makes_the_payslip_negative(self):
        Advance.objects.create(user=self.rahul, amount=Decimal("99000"),
                               given_on=date(YEAR, MONTH, 5))
        slip = self.run_payroll().payslips.get(user=self.rahul)
        self.assertEqual(slip.advance_deduction, Decimal("26000.00"))
        self.assertEqual(slip.net_payable, Decimal("0.00"))

    def test_recovered_advance_is_not_deducted_again(self):
        Advance.objects.create(user=self.rahul, amount=Decimal("5000"),
                               given_on=date(YEAR, MONTH, 5))
        services.finalise(self.run_payroll())
        run2 = PayrollRun.objects.create(year=YEAR, month=10)
        services.generate_run(run2, User.objects.filter(is_active=True))
        self.assertEqual(run2.payslips.get(user=self.rahul).advance_deduction, Decimal("0.00"))


class ApiTests(Base):
    def test_payroll_run_is_hr_only(self):
        self.as_(self.manager)
        self.assertEqual(self.client.post("/api/payroll-runs/",
                                          {"year": YEAR, "month": MONTH}).status_code, 403)
        self.as_(self.hr)
        res = self.client.post("/api/payroll-runs/", {"year": YEAR, "month": MONTH})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "draft")

    def test_duplicate_month_rejected_and_invalid_month_rejected(self):
        self.as_(self.hr)
        self.client.post("/api/payroll-runs/", {"year": YEAR, "month": MONTH})
        self.assertEqual(self.client.post("/api/payroll-runs/",
                                          {"year": YEAR, "month": MONTH}).status_code, 400)
        self.assertEqual(self.client.post("/api/payroll-runs/",
                                          {"year": YEAR, "month": 13}).status_code, 400)

    def test_finalise_locks_the_run(self):
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6:
                mark(self.rahul, day)
        self.as_(self.hr)
        run_id = self.client.post("/api/payroll-runs/", {"year": YEAR, "month": MONTH}).data["id"]
        res = self.client.post(f"/api/payroll-runs/{run_id}/finalise/")
        self.assertEqual(res.data["run"]["status"], "finalised")
        self.assertEqual(self.client.post(f"/api/payroll-runs/{run_id}/generate/").status_code, 400)
        self.assertEqual(self.client.post(f"/api/payroll-runs/{run_id}/finalise/").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/payroll-runs/{run_id}/").status_code, 400)

    def test_employee_sees_only_own_finalised_payslip(self):
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6:
                mark(self.rahul, day)
        run = self.run_payroll()
        self.as_(self.rahul)
        self.assertEqual(len(self.client.get("/api/payslips/").data), 0)   # draft hidden
        services.finalise(run)
        rows = self.client.get("/api/payslips/").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user"], self.rahul.id)
        # and cannot peek at anyone else
        self.assertEqual(len(self.client.get(f"/api/payslips/?user={self.manager.id}").data), 1)

    def test_salary_and_advances_are_hr_only_writes(self):
        self.as_(self.rahul)
        self.assertEqual(len(self.client.get("/api/salary-structures/").data), 1)  # own only
        res = self.client.post("/api/salary-structures/", {
            "user": self.rahul.id, "monthly_gross": "99000", "effective_from": "2026-01-05"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.post("/api/advances/", {
            "user": self.rahul.id, "amount": "500", "given_on": "2026-09-05"}).status_code, 403)
        self.as_(self.hr)
        self.assertEqual(self.client.post("/api/salary-structures/", {
            "user": self.manager.id, "monthly_gross": "30000",
            "effective_from": "2026-01-01"}).status_code, 201)
        self.assertEqual(self.client.post("/api/salary-structures/", {
            "user": self.manager.id, "monthly_gross": "0",
            "effective_from": "2026-02-01"}).status_code, 400)

    def test_csv_export(self):
        for day in range(1, 31):
            if date(YEAR, MONTH, day).weekday() != 6:
                mark(self.rahul, day)
        self.as_(self.hr)
        run_id = self.client.post("/api/payroll-runs/", {"year": YEAR, "month": MONTH}).data["id"]
        res = self.client.get(f"/api/payroll-runs/{run_id}/export/")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn("Employee,Username,Monthly gross", body)
        self.assertIn("26000.00", body)
        self.assertIn("TOTAL", body)
