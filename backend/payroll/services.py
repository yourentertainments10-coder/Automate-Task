"""Payroll computation — driven entirely by the attendance already recorded.

Day accounting for a month:
    working_days = calendar days − week-offs − holidays
    payable_days = present + late (full) + half-days (0.5) + approved PAID leave
    lwp_days     = working_days − payable_days        (loss of pay)
    earned_gross = monthly_gross × payable_days ÷ working_days

Deductions: PF% (on basic when set, else earned gross), professional tax,
any fixed deduction, and outstanding advances.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from crm.models import Holiday
from hr.models import Attendance, AttendanceStatus, LeaveRequest, LeaveStatus
from hr.services import is_week_off

from .models import Advance, Payslip, RunStatus, SalaryStructure

TWO = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def month_bounds(year: int, month: int):
    first = date(year, month, 1)
    last = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return first, last


def working_days_in(year: int, month: int) -> Decimal:
    """Calendar days minus weekly offs and company holidays."""
    first, last = month_bounds(year, month)
    holidays = set(Holiday.objects.filter(date__range=(first, last)).values_list("date", flat=True))
    count, cur = 0, first
    while cur <= last:
        if not is_week_off(cur) and cur not in holidays:
            count += 1
        cur += timedelta(days=1)
    return Decimal(count)


def structure_for(user, on_date: date):
    """The salary in force on that date (latest effective_from ≤ date)."""
    return (SalaryStructure.objects.filter(user=user, effective_from__lte=on_date)
            .order_by("-effective_from", "-id").first())


def paid_leave_dates(user, first: date, last: date) -> set:
    """Approved leave days of a PAID leave type inside the range."""
    out = set()
    leaves = LeaveRequest.objects.filter(
        user=user, status=LeaveStatus.APPROVED, leave_type__paid=True,
        start_date__lte=last, end_date__gte=first,
    ).select_related("leave_type")
    for leave in leaves:
        cur = max(leave.start_date, first)
        stop = min(leave.end_date, last)
        while cur <= stop:
            out.add(cur)
            cur += timedelta(days=1)
    return out


def count_days(user, year: int, month: int, working_days: Decimal) -> dict:
    """Turn a month of attendance into payable days."""
    first, last = month_bounds(year, month)
    records = {a.date: a for a in Attendance.objects.filter(user=user, date__range=(first, last))}
    paid_leaves = paid_leave_dates(user, first, last)

    present = half = paid_leave = unpaid_leave = 0
    for day, rec in records.items():
        if is_week_off(day):
            continue
        if rec.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE):
            present += 1
        elif rec.status == AttendanceStatus.HALF_DAY:
            half += 1
        elif rec.status == AttendanceStatus.LEAVE:
            if day in paid_leaves:
                paid_leave += 1
            else:
                unpaid_leave += 1

    payable = Decimal(present) + (Decimal(half) / 2) + Decimal(paid_leave)
    payable = min(payable, working_days)
    lwp = max(Decimal(0), working_days - payable)
    return {
        "present": present, "half_day": half, "paid_leave": paid_leave,
        "unpaid_leave": unpaid_leave,
        "payable_days": payable, "lwp_days": lwp,
    }


def build_payslip(run, user) -> Payslip | None:
    """Compute (or recompute) one employee's payslip for a draft run.
    Returns None when the employee has no salary structure yet."""
    first, last = month_bounds(run.year, run.month)
    structure = structure_for(user, last)
    if not structure:
        return None

    working_days = run.working_days or working_days_in(run.year, run.month)
    days = count_days(user, run.year, run.month, working_days)

    gross = money(structure.monthly_gross)
    per_day = gross / working_days if working_days else Decimal(0)
    earned = money(per_day * days["payable_days"])

    # PF is charged on EARNED basic, not the full month's basic -- someone who
    # worked half the month pays PF on half the basic.
    ratio = (days["payable_days"] / working_days) if working_days else Decimal(0)
    pf_base = money(Decimal(structure.basic) * ratio) if structure.basic else earned
    pf = money(pf_base * Decimal(structure.pf_percent) / 100) if structure.pf_percent else money(0)
    ptax = money(structure.professional_tax) if earned > 0 else money(0)
    other = money(structure.other_deduction) if earned > 0 else money(0)

    # A payslip can never go negative: if the fixed deductions exceed what was
    # earned, drop them in reverse priority (other, then PT, then PF).
    excess = (pf + ptax + other) - earned
    if excess > 0:
        for name in ("other", "ptax", "pf"):
            if excess <= 0:
                break
            current = {"other": other, "ptax": ptax, "pf": pf}[name]
            cut = min(current, excess)
            if name == "other":
                other -= cut
            elif name == "ptax":
                ptax -= cut
            else:
                pf -= cut
            excess -= cut

    advances = list(Advance.objects.filter(user=user, recovered=False, given_on__lte=last))
    advance_total = money(sum((a.amount for a in advances), Decimal(0)))
    # Never push a payslip negative -- recover only what this month can bear.
    recoverable = min(advance_total, max(Decimal(0), earned - pf - ptax - other))

    net = money(earned - pf - ptax - other - recoverable)

    slip, _ = Payslip.objects.update_or_create(
        run=run, user=user,
        defaults={
            "monthly_gross": gross,
            "working_days": working_days,
            "payable_days": days["payable_days"],
            "lwp_days": days["lwp_days"],
            "earned_gross": earned,
            "pf": pf, "professional_tax": ptax,
            "advance_deduction": money(recoverable), "other_deduction": other,
            "net_payable": net,
            "breakdown": {
                **{k: (float(v) if isinstance(v, Decimal) else v) for k, v in days.items()},
                "per_day": float(money(per_day)),
                "advance_outstanding": float(advance_total),
                "structure_id": structure.pk,
            },
        },
    )
    return slip


def generate_run(run, users) -> dict:
    """(Re)build every payslip in a draft run."""
    if run.status == RunStatus.FINALISED:
        raise ValueError("This payroll is finalised and cannot be recalculated.")
    run.working_days = working_days_in(run.year, run.month)
    made, skipped = 0, []
    for user in users:
        slip = build_payslip(run, user)
        if slip:
            made += 1
        else:
            skipped.append(user.get_full_name() or user.username)
    run.total_net = money(sum((s.net_payable for s in run.payslips.all()), Decimal(0)))
    run.save(update_fields=["working_days", "total_net"])
    return {"payslips": made, "skipped_no_salary": skipped}


def finalise(run) -> dict:
    """Lock the run and mark the recovered advances as settled."""
    if run.status == RunStatus.FINALISED:
        raise ValueError("This payroll is already finalised.")
    if not run.payslips.exists():
        raise ValueError("Generate the payslips before finalising.")
    recovered = 0
    for slip in run.payslips.select_related("user"):
        if slip.advance_deduction <= 0:
            continue
        remaining = slip.advance_deduction
        for adv in Advance.objects.filter(user=slip.user, recovered=False,
                                          given_on__lte=month_bounds(run.year, run.month)[1]):
            if remaining <= 0:
                break
            if adv.amount <= remaining:
                adv.recovered = True
                adv.recovered_in = slip
                adv.save(update_fields=["recovered", "recovered_in"])
                remaining -= adv.amount
                recovered += 1
    run.status = RunStatus.FINALISED
    run.finalised_at = timezone.now()
    run.save(update_fields=["status", "finalised_at"])
    return {"advances_settled": recovered}
