import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import AssignmentRule, Lead, Task
from notifications.models import Notification

from .models import Form, FormField, FormSubmission

MEDIA_TMP = tempfile.mkdtemp()


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def build_quote_form(self, **form_kw):
        """The spec's example: quotation request form mapped to a Lead."""
        form = Form.objects.create(name="Request a quotation", created_by=self.manager,
                                   status="published", **form_kw)
        self.f_name = FormField.objects.create(form=form, label="Name", type="short_text",
                                               required=True, lead_attr="customer_name", order=0)
        self.f_phone = FormField.objects.create(form=form, label="Phone", type="phone",
                                                required=True, lead_attr="phone", order=1)
        self.f_req = FormField.objects.create(form=form, label="Requirement", type="long_text",
                                              lead_attr="requirement", order=2)
        return form


class BuilderTests(Base):
    def test_exec_cannot_create_manager_can(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.post("/api/forms/", {"name": "X"}).status_code, 403)
        self.as_(self.manager)
        res = self.client.post("/api/forms/", {"name": "Website Inquiry"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "draft")
        self.assertTrue(res.data["public_token"])

    def test_field_add_edit_reorder_delete(self):
        self.as_(self.manager)
        form_id = self.client.post("/api/forms/", {"name": "F"}).data["id"]
        a = self.client.post(f"/api/forms/{form_id}/add_field/",
                             {"label": "Name", "type": "short_text", "required": True}).data
        b = self.client.post(f"/api/forms/{form_id}/add_field/",
                             {"label": "City", "type": "dropdown", "options": ["Delhi", "Mumbai"]},
                             format="json").data
        # dropdown without options is rejected
        bad = self.client.post(f"/api/forms/{form_id}/add_field/",
                               {"label": "Bad", "type": "radio", "options": []}, format="json")
        self.assertEqual(bad.status_code, 400)
        # edit
        res = self.client.patch(f"/api/form-fields/{a['id']}/", {"label": "Full name"})
        self.assertEqual(res.data["label"], "Full name")
        # reorder (b first)
        res = self.client.post(f"/api/forms/{form_id}/reorder_fields/",
                               {"order": [b["id"], a["id"]]}, format="json")
        self.assertEqual([f["label"] for f in res.data["fields"]], ["City", "Full name"])
        # delete
        self.assertEqual(self.client.delete(f"/api/form-fields/{a['id']}/").status_code, 204)

    def test_publish_requires_fields_and_other_manager_blocked(self):
        self.as_(self.manager)
        form_id = self.client.post("/api/forms/", {"name": "F"}).data["id"]
        self.assertEqual(self.client.post(f"/api/forms/{form_id}/publish/").status_code, 400)
        self.client.post(f"/api/forms/{form_id}/add_field/", {"label": "N", "type": "short_text"})
        self.assertEqual(self.client.post(f"/api/forms/{form_id}/publish/").data["status"], "published")
        other = make("sonal", Role.SALES_MANAGER)
        self.as_(other)
        self.assertEqual(self.client.post(f"/api/forms/{form_id}/close/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/forms/{form_id}/submissions/").status_code, 403)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class SubmissionTests(Base):
    def test_public_get_and_submit_draft_hidden(self):
        form = self.build_quote_form()
        res = self.client.get(f"/api/public/forms/{form.public_token}/")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("public_token", res.data)
        form.status = "draft"
        form.save()
        self.assertEqual(self.client.get(f"/api/public/forms/{form.public_token}/").status_code, 404)

    def test_validation_errors(self):
        form = self.build_quote_form()
        url = f"/api/public/forms/{form.public_token}/submit/"
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn(str(self.f_name.id), res.data)
        res = self.client.post(url, {str(self.f_name.id): "Ravi",
                                     str(self.f_phone.id): "not-a-phone"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid phone", res.data[str(self.f_phone.id)])

    def test_closed_form_rejects_submissions(self):
        form = self.build_quote_form()
        form.status = "closed"
        form.save()
        res = self.client.post(f"/api/public/forms/{form.public_token}/submit/",
                               {str(self.f_name.id): "Ravi"}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_employee_submit_records_user(self):
        form = self.build_quote_form()
        self.as_(self.rahul)
        res = self.client.post(f"/api/forms/{form.id}/submit/",
                               {str(self.f_name.id): "Ravi", str(self.f_phone.id): "9876543210"},
                               format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(FormSubmission.objects.get().submitted_by, self.rahul)

    def test_file_upload_and_size_cap(self):
        form = self.build_quote_form()
        f_file = FormField.objects.create(form=form, label="Attachment", type="file", order=3)
        res = self.client.post(
            f"/api/public/forms/{form.public_token}/submit/",
            {str(self.f_name.id): "Ravi", str(self.f_phone.id): "9876543210",
             f"file_{f_file.id}": SimpleUploadedFile("spec.pdf", b"pdf-bytes")},
            format="multipart")
        self.assertEqual(res.status_code, 201)
        sub = FormSubmission.objects.get()
        self.assertEqual(sub.files.count(), 1)
        self.assertEqual(sub.files.first().filename, "spec.pdf")


class IntegrationTests(Base):
    def setUp(self):
        super().setUp()
        AssignmentRule.objects.create(department="sales", strategy="round_robin",
                                      member_ids=[self.rahul.pk, self.amit.pk])

    def test_form_creates_lead_and_reuses_auto_assignment(self):
        form = self.build_quote_form(create_lead=True, lead_department="sales")
        res = self.client.post(f"/api/public/forms/{form.public_token}/submit/", {
            str(self.f_name.id): "Ravi Kumar",
            str(self.f_phone.id): "9876543210",
            str(self.f_req.id): "Tata 407 brake pads",
        }, format="json")
        self.assertEqual(res.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(lead.customer_name, "Ravi Kumar")
        self.assertEqual(lead.phone, "9876543210")
        self.assertEqual(lead.requirement, "Tata 407 brake pads")
        self.assertEqual(lead.source, "web")
        self.assertEqual(lead.assigned_to, self.rahul)  # existing round-robin
        self.assertTrue(lead.events.filter(body__contains="Auto-assigned").exists())
        self.assertTrue(Notification.objects.filter(user=self.rahul, type="lead_assigned").exists())
        # rotation advanced: second submission goes to amit
        self.client.post(f"/api/public/forms/{form.public_token}/submit/", {
            str(self.f_name.id): "Second", str(self.f_phone.id): "9876543211",
        }, format="json")
        self.assertEqual(Lead.objects.get(customer_name="Second").assigned_to, self.amit)

    def test_form_creates_followup_task_for_lead_assignee(self):
        form = self.build_quote_form(create_lead=True, create_task=True,
                                     task_title="Call back the customer")
        self.client.post(f"/api/public/forms/{form.public_token}/submit/", {
            str(self.f_name.id): "Ravi", str(self.f_phone.id): "9876543210",
        }, format="json")
        task = Task.objects.get()
        self.assertEqual(task.title, "Call back the customer")
        self.assertEqual(task.assigned_to, self.rahul)      # follows the lead assignee
        self.assertEqual(task.lead, Lead.objects.get())
        self.assertIsNotNone(task.due_at)
        self.assertTrue(Notification.objects.filter(user=self.rahul, type="task_assigned").exists())

    def test_task_only_form_assigns_to_creator(self):
        form = self.build_quote_form(create_task=True)
        self.client.post(f"/api/public/forms/{form.public_token}/submit/", {
            str(self.f_name.id): "Ravi", str(self.f_phone.id): "9876543210",
        }, format="json")
        self.assertEqual(Task.objects.get().assigned_to, self.manager)
        self.assertEqual(Lead.objects.count(), 0)


class ExportTests(Base):
    def test_csv_export(self):
        form = self.build_quote_form()
        self.client.post(f"/api/public/forms/{form.public_token}/submit/", {
            str(self.f_name.id): "Ravi", str(self.f_phone.id): "9876543210",
            str(self.f_req.id): "Brake pads",
        }, format="json")
        self.as_(self.manager)
        res = self.client.get(f"/api/forms/{form.id}/export/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "text/csv")
        body = res.content.decode()
        self.assertIn("Submission ID,Date,Person,Lead,Task,Name,Phone,Requirement", body)
        self.assertIn("Ravi,9876543210,Brake pads", body)

    def test_submissions_listing(self):
        form = self.build_quote_form()
        self.client.post(f"/api/public/forms/{form.public_token}/submit/",
                         {str(self.f_name.id): "Ravi", str(self.f_phone.id): "9876543210"},
                         format="json")
        self.as_(self.manager)
        rows = self.client.get(f"/api/forms/{form.id}/submissions/").data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person"], "Ravi")
        self.assertEqual(rows[0]["answers"][str(self.f_name.id)], "Ravi")
