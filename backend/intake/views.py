from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasCapability

from .models import InboundMessage
from .pipeline import process_message


class InboundMessageSerializer(serializers.ModelSerializer):
    lead_name = serializers.CharField(source="lead.customer_name", read_only=True, default=None)

    class Meta:
        model = InboundMessage
        fields = ["id", "channel", "sender", "sender_name", "subject", "body",
                  "media", "ai_result", "lead", "lead_name", "status", "error",
                  "created_at", "processed_at"]


class SimulateSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=["whatsapp", "gmail"])
    sender = serializers.CharField(max_length=200)
    sender_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    subject = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    body = serializers.CharField(max_length=8000)


class IntakeViewSet(viewsets.ReadOnlyModelViewSet):
    """AI inbox: what came in, how it was classified, which lead it became."""
    permission_classes = [HasCapability.of("intake.view")]
    serializer_class = InboundMessageSerializer
    queryset = InboundMessage.objects.select_related("lead").all()

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("channel"):
            qs = qs.filter(channel=p["channel"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    @action(detail=False, methods=["post"],
            permission_classes=[HasCapability.of("settings.manage")])
    def simulate(self, request):
        """Admin-only: run any text through the REAL pipeline without the
        live webhook -- for testing and demos."""
        ser = SimulateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        n = InboundMessage.objects.filter(channel=d["channel"], external_id__startswith="sim-").count()
        msg = InboundMessage.objects.create(
            channel=d["channel"], external_id=f"sim-{d['channel']}-{n + 1}",
            sender=d["sender"], sender_name=d["sender_name"],
            subject=d["subject"], body=d["body"],
        )
        process_message(msg)
        return Response(InboundMessageSerializer(msg).data, status=status.HTTP_201_CREATED)
