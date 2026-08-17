"""Submission validation + the lead/task integrations.

The integrations deliberately REUSE existing machinery: crm.assignment.
auto_assign for lead routing and notifications.service.notify for the
task ping -- no second pipeline.
"""
import re
from datetime import date, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.utils import timezone

from crm.assignment import auto_assign
from crm.models import EventType, Lead, LeadEvent, Task
from notifications.service import notify

from .models import FieldType, Form, FormSubmission, SubmissionFile

MAX_FILE_MB = 10
PHONE_RE = re.compile(r"^\+?[\d ()\-]{7,20}$")


def validate_answers(form: Form, data: dict, files: dict):
    """Returns (answers, file_map, errors). `data` values come in as strings
    (or lists for checkbox); `files` is {field_id(str): UploadedFile}."""
    answers, file_map, errors = {}, {}, {}
    for field in form.fields.all():
        key = str(field.id)
        raw = data.get(key)

        if field.type == FieldType.FILE:
            f = files.get(key)
            if field.required and not f:
                errors[key] = f"{field.label} is required."
            elif f:
                if f.size > MAX_FILE_MB * 1024 * 1024:
                    errors[key] = f"{field.label}: file exceeds {MAX_FILE_MB} MB."
                else:
                    file_map[key] = f
                    answers[key] = f.name
            continue

        if field.type == FieldType.CHECKBOX:
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            values = [v for v in values if v]
            if field.required and not values:
                errors[key] = f"{field.label} is required."
            elif values and not set(values).issubset(set(field.options)):
                errors[key] = f"{field.label}: invalid choice."
            else:
                answers[key] = values
            continue

        value = (raw or "").strip() if isinstance(raw, str) else raw
        if not value:
            if field.required:
                errors[key] = f"{field.label} is required."
            continue
        value = str(value)

        if field.type == FieldType.EMAIL:
            try:
                validate_email(value)
            except DjangoValidationError:
                errors[key] = f"{field.label}: invalid email."
                continue
        elif field.type == FieldType.PHONE:
            if not PHONE_RE.match(value):
                errors[key] = f"{field.label}: invalid phone number."
                continue
        elif field.type == FieldType.NUMBER:
            try:
                float(value)
            except ValueError:
                errors[key] = f"{field.label}: must be a number."
                continue
        elif field.type == FieldType.DATE:
            try:
                date.fromisoformat(value)
            except ValueError:
                errors[key] = f"{field.label}: use YYYY-MM-DD."
                continue
        elif field.type in (FieldType.DROPDOWN, FieldType.RADIO):
            if value not in field.options:
                errors[key] = f"{field.label}: invalid choice."
                continue
        answers[key] = value[:4000]
    return answers, file_map, errors


def create_submission(form: Form, data: dict, files: dict, user=None) -> FormSubmission:
    """Validate, store, then run the lead/task integrations. Raises
    ValueError with a {field: msg} dict when validation fails."""
    answers, file_map, errors = validate_answers(form, data, files)
    if errors:
        raise ValueError(errors)
    submission = FormSubmission.objects.create(
        form=form, answers=answers,
        submitted_by=user if (user and user.is_authenticated) else None,
    )
    for key, f in file_map.items():
        SubmissionFile.objects.create(submission=submission, field_id=int(key),
                                      file=f, filename=f.name)
    _run_integrations(submission)
    return submission


def _run_integrations(submission: FormSubmission):
    form = submission.form
    lead = None

    if form.create_lead:
        mapped = {}
        for field in form.fields.exclude(lead_attr=""):
            value = submission.answers.get(str(field.id))
            if value:
                mapped[field.lead_attr] = ", ".join(value) if isinstance(value, list) else str(value)
        lead = Lead.objects.create(
            customer_name=(mapped.get("customer_name") or submission.person() or "Form submission")[:200],
            phone=mapped.get("phone", "")[:30],
            email=mapped.get("email", "")[:250],
            company=mapped.get("company", "")[:200],
            requirement=(mapped.get("requirement") or f"Submission of form '{form.name}'")[:2000],
            source="web",
            department=form.lead_department,
        )
        LeadEvent.objects.create(
            lead=lead, type=EventType.CREATED,
            body=f"Lead created from form '{form.name}'",
            payload={"form_id": form.pk, "submission_id": submission.pk},
        )
        auto_assign(lead)  # the EXISTING engine: department rule, events, notification
        submission.lead = lead

    if form.create_task:
        assignee = (lead.assigned_to if lead and lead.assigned_to else form.created_by)
        if assignee:
            task = Task.objects.create(
                title=(form.task_title or f"Follow up: {form.name}")[:200],
                description=f"Auto-created from form '{form.name}' submission #{submission.pk}",
                assigned_to=assignee, created_by=form.created_by,
                lead=lead, due_at=timezone.now() + timedelta(days=1),
            )
            notify(
                assignee, "task_assigned",
                f"Task assigned: {task.title}",
                f"New submission on form '{form.name}'"
                + (f" -- lead: {lead.customer_name}" if lead else ""),
                link="/tasks",
            )
            submission.task = task

    if submission.lead or submission.task:
        submission.save(update_fields=["lead", "task"])
