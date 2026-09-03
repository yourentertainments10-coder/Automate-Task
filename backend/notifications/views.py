from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer

from .models import Notification


class NotificationSerializer(ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "title", "body", "link", "channels", "read_at", "created_at"]


class NotificationViewSet(mixins.DestroyModelMixin,
                          viewsets.ReadOnlyModelViewSet):
    """Own notifications only -- there is deliberately no way to query, or
    clear, someone else's feed. Clearing really deletes the row: a
    notification is a delivered message, not a record anyone audits, and
    people asked to be able to empty the list for good."""
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(read_at__isnull=True).count()})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        n = self.get_object()
        if not n.read_at:
            n.read_at = timezone.now()
            n.save(update_fields=["read_at"])
        return Response(NotificationSerializer(n).data)

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        updated = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"marked": updated})

    @action(detail=False, methods=["post"])
    def clear(self, request):
        """Empty this person's notification list for good.

        ?only=read clears just the ones they have already seen, so an unread
        alert is never swept away by a tap meant to tidy up. The rows are
        deleted, not hidden -- nothing is left behind in the database.
        """
        qs = self.get_queryset()
        if request.query_params.get("only") == "read" or request.data.get("only") == "read":
            qs = qs.filter(read_at__isnull=False)
        deleted, _ = qs.delete()
        return Response({"deleted": deleted})
