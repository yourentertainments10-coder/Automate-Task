from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Role, User
from accounts.permissions import IsAdmin, has_capability

from notifications.service import notify_lead_assigned, notify_status_change

from .assignment import auto_assign
from .models import AssignmentRule, EventType, Lead, LeadEvent, LeadStatus, OPEN_STATUSES, Quotation
from .scoping import can_assign, can_edit_lead, visible_leads
from .serializers import (
    AssignmentRuleSerializer, LeadDocumentSerializer, LeadEventSerializer,
    LeadSerializer, NoteSerializer, QuotationSerializer, UserBriefSerializer,
)

MAX_DOC_MB = 10


def log(lead, type_, actor=None, body="", payload=None):
    return LeadEvent.objects.create(lead=lead, type=type_, actor=actor, body=body, payload=payload or {})


class LeadViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LeadSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = visible_leads(self.request.user)
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("priority"):
            qs = qs.filter(priority=p["priority"])
        if p.get("source"):
            qs = qs.filter(source=p["source"])
        if p.get("assigned_to"):
            qs = qs.filter(assigned_to_id=p["assigned_to"])
        if p.get("department"):
            qs = qs.filter(department=p["department"])
        if p.get("overdue") == "true":
            qs = qs.filter(status__in=OPEN_STATUSES, follow_up_at__lt=timezone.now())
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(
                Q(customer_name__icontains=s) | Q(company__icontains=s)
                | Q(phone__icontains=s) | Q(email__icontains=s) | Q(requirement__icontains=s)
            )
        return qs

    # ---- create / update ------------------------------------------------
    def perform_create(self, serializer):
        user = self.request.user
        assigned = serializer.validated_data.get("assigned_to")
        if assigned and assigned.pk != user.pk and not can_assign(user):
            raise PermissionDenied("Your role cannot assign leads to other people.")
        if not assigned and has_capability(user, "leads.view_own"):
            serializer.validated_data["assigned_to"] = user  # execs default to themselves
        lead = serializer.save(created_by=user)
        log(lead, EventType.CREATED, user, f"Lead created ({lead.get_source_display()})")
        if lead.assigned_to:
            log(lead, EventType.ASSIGNMENT, user, f"Assigned to {lead.assigned_to.get_full_name() or lead.assigned_to.username}",
                {"assigned_to": lead.assigned_to_id})
            notify_lead_assigned(lead, actor=user)
        else:
            auto_assign(lead, actor=user)  # department rule (round-robin/fixed), no-op if no rule

    def perform_update(self, serializer):
        user = self.request.user
        lead = self.get_object()
        if not can_edit_lead(user, lead):
            raise PermissionDenied("You cannot edit this lead.")
        old_status, old_assignee, old_follow = lead.status, lead.assigned_to, lead.follow_up_at

        new_assignee = serializer.validated_data.get("assigned_to", old_assignee)
        if new_assignee != old_assignee and not can_assign(user):
            raise PermissionDenied("Your role cannot reassign leads.")

        updated = serializer.save()

        if updated.status != old_status:
            log(updated, EventType.STATUS_CHANGE, user,
                f"{LeadStatus(old_status).label} -> {updated.get_status_display()}",
                {"from": old_status, "to": updated.status})
            notify_status_change(updated, user, LeadStatus(old_status).label)
        if updated.assigned_to != old_assignee:
            name = (updated.assigned_to.get_full_name() or updated.assigned_to.username) if updated.assigned_to else "Unassigned"
            log(updated, EventType.ASSIGNMENT, user, f"Assigned to {name}",
                {"assigned_to": updated.assigned_to_id})
            notify_lead_assigned(updated, actor=user)
        if updated.follow_up_at != old_follow:
            body = f"Follow-up set for {timezone.localtime(updated.follow_up_at):%d %b %Y %H:%M}" if updated.follow_up_at else "Follow-up cleared"
            log(updated, EventType.FOLLOW_UP, user, body)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != Role.ADMIN:
            raise PermissionDenied("Only an admin can delete a lead.")
        return super().destroy(request, *args, **kwargs)

    # ---- sub-resources --------------------------------------------------
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        lead = self.get_object()
        return Response(LeadEventSerializer(lead.events.select_related("actor"), many=True).data)

    @action(detail=True, methods=["post"])
    def notes(self, request, pk=None):
        lead = self.get_object()
        if not can_edit_lead(request.user, lead):
            raise PermissionDenied("You cannot add notes to this lead.")
        ser = NoteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        event = log(lead, EventType.NOTE, request.user, ser.validated_data["body"])
        return Response(LeadEventSerializer(event).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def documents(self, request, pk=None):
        lead = self.get_object()
        if request.method == "GET":
            return Response(LeadDocumentSerializer(lead.documents.select_related("uploaded_by"), many=True).data)
        if not can_edit_lead(request.user, lead):
            raise PermissionDenied("You cannot attach documents to this lead.")
        file = request.FILES.get("file")
        if not file:
            raise ValidationError({"file": "No file uploaded."})
        if file.size > MAX_DOC_MB * 1024 * 1024:
            raise ValidationError({"file": f"File exceeds {MAX_DOC_MB} MB."})
        doc = lead.documents.create(file=file, filename=file.name, uploaded_by=request.user)
        log(lead, EventType.DOCUMENT, request.user, f"Uploaded {file.name}", {"document_id": doc.id})
        return Response(LeadDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def quotations(self, request, pk=None):
        lead = self.get_object()
        if request.method == "GET":
            return Response(QuotationSerializer(lead.quotations.select_related("created_by"), many=True).data)
        if not has_capability(request.user, "quotations.manage") or not can_edit_lead(request.user, lead):
            raise PermissionDenied("You cannot add quotations to this lead.")
        ser = QuotationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        q = ser.save(lead=lead, created_by=request.user)
        log(lead, EventType.QUOTATION, request.user,
            f"Quotation {q.number} for Rs.{q.amount}", {"quotation_id": q.id, "status": q.status})
        return Response(QuotationSerializer(q).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = visible_leads(request.user)
        by_status = {s: 0 for s, _ in LeadStatus.choices}
        for row in qs.values("status"):
            by_status[row["status"]] += 1
        overdue = qs.filter(status__in=OPEN_STATUSES, follow_up_at__lt=timezone.now()).count()
        return Response({"by_status": by_status, "total": qs.count(), "overdue": overdue})

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        """Active users the current user may assign leads to (for dropdowns)."""
        users = User.objects.filter(is_active=True).order_by("first_name", "username")
        return Response(UserBriefSerializer(users, many=True).data)


class AssignmentRuleViewSet(viewsets.ModelViewSet):
    """Admin-only auto-assignment rules (one per department)."""
    permission_classes = [IsAdmin]
    serializer_class = AssignmentRuleSerializer
    queryset = AssignmentRule.objects.all().order_by("department")
    pagination_class = None

    def perform_update(self, serializer):
        # Changing members/strategy restarts the rotation from the top.
        rule = serializer.instance
        if serializer.validated_data.get("member_ids", rule.member_ids) != rule.member_ids:
            serializer.validated_data["rr_index"] = 0
        serializer.save()


class QuotationViewSet(viewsets.GenericViewSet):
    """PATCH /api/quotations/:id -- status/notes updates, guarded by lead access."""
    permission_classes = [IsAuthenticated]
    serializer_class = QuotationSerializer

    def get_queryset(self):
        return Quotation.objects.filter(lead__in=visible_leads(self.request.user))

    def partial_update(self, request, pk=None):
        q = self.get_object()
        if not has_capability(request.user, "quotations.manage") or not can_edit_lead(request.user, q.lead):
            raise PermissionDenied("You cannot modify this quotation.")
        old_status = q.status
        ser = QuotationSerializer(q, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        q = ser.save()
        if q.status != old_status:
            log(q.lead, EventType.QUOTATION, request.user,
                f"Quotation {q.number}: {old_status} -> {q.status}", {"quotation_id": q.id, "status": q.status})
        return Response(QuotationSerializer(q).data)
