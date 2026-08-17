import csv

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import has_capability

from .models import Form, FormField, FormStatus
from .serializers import (
    FormFieldSerializer, FormSerializer, PublicFormSerializer, SubmissionSerializer,
)
from .services import create_submission


def can_build_forms(user) -> bool:
    return has_capability(user, "tasks.assign")  # admin + managers


def can_manage_form(user, form: Form) -> bool:
    return has_capability(user, "tasks.view_all") or form.created_by_id == user.id


def _extract_payload(request):
    """Normalise JSON and multipart bodies into (data, files).
    Multipart checkbox answers arrive as repeated keys; files as file_<id>."""
    files = {}
    for key, f in request.FILES.items():
        files[key.replace("file_", "", 1)] = f
    if hasattr(request.data, "getlist"):  # QueryDict (multipart/form)
        data = {}
        for key in request.data:
            if key.startswith("file_"):
                continue
            values = request.data.getlist(key)
            data[key] = values if len(values) > 1 else values[0]
    else:
        data = {k: v for k, v in request.data.items() if not str(k).startswith("file_")}
    return data, files


class FormViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = FormSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if self.request.query_params.get("manage") == "true":
            if not can_build_forms(user):
                raise PermissionDenied("Your role cannot manage forms.")
            qs = Form.objects.select_related("created_by").prefetch_related("fields")
            if has_capability(user, "tasks.view_all"):
                return qs
            return qs.filter(created_by=user)
        # default: published forms anyone signed-in can fill
        return (Form.objects.filter(status=FormStatus.PUBLISHED)
                .select_related("created_by").prefetch_related("fields"))

    def get_object(self):
        """Detail lookups must also reach the owner's DRAFT forms (the whole
        builder works on drafts); non-owners only ever see published ones."""
        form = (Form.objects.select_related("created_by").prefetch_related("fields")
                .filter(pk=self.kwargs["pk"]).first())
        if not form:
            raise NotFound("Form not found.")
        if form.status == FormStatus.PUBLISHED or can_manage_form(self.request.user, form):
            return form
        raise NotFound("Form not found.")

    def perform_create(self, serializer):
        if not can_build_forms(self.request.user):
            raise PermissionDenied("Your role cannot create forms.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        if not can_manage_form(self.request.user, self.get_object()):
            raise PermissionDenied("You can only edit your own forms.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_form(self.request.user, instance):
            raise PermissionDenied("You can only delete your own forms.")
        if instance.submissions.exists():
            raise ValidationError({"detail": "This form has submissions -- close it instead of deleting."})
        instance.delete()

    def _set_status(self, request, pk, new_status):
        form = Form.objects.get(pk=pk)
        if not can_manage_form(request.user, form):
            raise PermissionDenied("You can only manage your own forms.")
        if new_status == FormStatus.PUBLISHED and not form.fields.exists():
            raise ValidationError({"detail": "Add at least one field before publishing."})
        form.status = new_status
        form.save(update_fields=["status", "updated_at"])
        return Response(FormSerializer(form, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._set_status(request, pk, FormStatus.PUBLISHED)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self._set_status(request, pk, FormStatus.CLOSED)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        return self._set_status(request, pk, FormStatus.PUBLISHED)

    # ---- builder: fields -------------------------------------------------
    @action(detail=True, methods=["post"])
    def add_field(self, request, pk=None):
        form = self.get_object()
        if not can_manage_form(request.user, form):
            raise PermissionDenied("You can only edit your own forms.")
        ser = FormFieldSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        last = form.fields.order_by("-order").first()
        field = ser.save(form=form, order=(last.order + 1) if last else 0)
        return Response(FormFieldSerializer(field).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reorder_fields(self, request, pk=None):
        form = self.get_object()
        if not can_manage_form(request.user, form):
            raise PermissionDenied("You can only edit your own forms.")
        ids = request.data.get("order") or []
        known = {f.id: f for f in form.fields.all()}
        if set(ids) != set(known):
            raise ValidationError({"order": "Must contain exactly the form's field ids."})
        for pos, fid in enumerate(ids):
            FormField.objects.filter(pk=fid).update(order=pos)
        return Response(FormSerializer(Form.objects.get(pk=pk), context={"request": request}).data)

    # ---- submissions -----------------------------------------------------
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """Signed-in (employee) submission of a published form."""
        form = Form.objects.filter(pk=pk, status=FormStatus.PUBLISHED).first()
        if not form:
            raise ValidationError({"detail": "This form is not accepting submissions."})
        data, files = _extract_payload(request)
        try:
            sub = create_submission(form, data, files, user=request.user)
        except ValueError as exc:
            return Response(exc.args[0], status=400)
        return Response(SubmissionSerializer(sub).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def submissions(self, request, pk=None):
        form = Form.objects.get(pk=pk)
        if not can_manage_form(request.user, form):
            raise PermissionDenied("Only the form owner or an admin can view submissions.")
        subs = form.submissions.select_related("submitted_by", "lead", "task").prefetch_related("files")
        return Response(SubmissionSerializer(subs, many=True).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        form = Form.objects.get(pk=pk)
        if not can_manage_form(request.user, form):
            raise PermissionDenied("Only the form owner or an admin can export submissions.")
        fields = list(form.fields.all())
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{form.name[:40]}-submissions.csv"'
        writer = csv.writer(response)
        writer.writerow(["Submission ID", "Date", "Person", "Lead", "Task"]
                        + [f.label for f in fields])
        for sub in form.submissions.select_related("submitted_by", "lead", "task"):
            row = [sub.pk, sub.created_at.strftime("%Y-%m-%d %H:%M"), sub.person(),
                   sub.lead.customer_name if sub.lead else "", sub.task.title if sub.task else ""]
            for f in fields:
                v = sub.answers.get(str(f.id), "")
                row.append(", ".join(v) if isinstance(v, list) else v)
            writer.writerow(row)
        return response


class FormFieldViewSet(viewsets.GenericViewSet):
    """PATCH/DELETE a single field (builder edit/delete)."""
    permission_classes = [IsAuthenticated]
    serializer_class = FormFieldSerializer
    queryset = FormField.objects.select_related("form")

    def partial_update(self, request, pk=None):
        field = self.get_object()
        if not can_manage_form(request.user, field.form):
            raise PermissionDenied("You can only edit your own forms.")
        ser = FormFieldSerializer(field, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        return Response(FormFieldSerializer(ser.save()).data)

    def destroy(self, request, pk=None):
        field = self.get_object()
        if not can_manage_form(request.user, field.form):
            raise PermissionDenied("You can only edit your own forms.")
        field.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- public (share-link) endpoints ---------------------------------------

@api_view(["GET"])
@permission_classes([AllowAny])
def public_form(request, token):
    form = Form.objects.filter(public_token=token, status=FormStatus.PUBLISHED).first()
    if not form:
        return Response({"detail": "Form not found or not accepting submissions."}, status=404)
    return Response(PublicFormSerializer(form).data)


@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def public_submit(request, token):
    form = Form.objects.filter(public_token=token, status=FormStatus.PUBLISHED).first()
    if not form:
        return Response({"detail": "Form not found or not accepting submissions."}, status=404)
    data, files = _extract_payload(request)
    try:
        sub = create_submission(form, data, files,
                                user=request.user if request.user.is_authenticated else None)
    except ValueError as exc:
        return Response(exc.args[0], status=400)
    return Response({"detail": "Thank you! Your response has been recorded.", "id": sub.pk},
                    status=status.HTTP_201_CREATED)
