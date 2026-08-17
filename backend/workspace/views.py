from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasCapability
from crm.models import Task, TaskActivity, TaskStatus
from crm.serializers import UserBriefSerializer

from .access import (
    can_create_group, can_edit_link, can_manage_group, can_review_ideas,
    notice_targets, notices_for, user_group_ids, visible_groups, visible_ideas,
    visible_links,
)
from .models import (
    Group, Idea, IdeaComment, Link, LinkCollection, Notice, NoticeRead,
    NoticeStatus,
)
from .serializers import (
    GroupSerializer, IdeaCommentSerializer, IdeaSerializer,
    LinkCollectionSerializer, LinkSerializer, NoticeSerializer,
)


class GroupViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = GroupSerializer
    pagination_class = None

    def get_queryset(self):
        qs = visible_groups(self.request.user)
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(active=True)
        return qs

    def perform_create(self, serializer):
        if not can_create_group(self.request.user):
            raise PermissionDenied("Your role cannot create groups.")
        group = serializer.save(owner=self.request.user)
        group.members.add(self.request.user)

    def perform_update(self, serializer):
        if not can_manage_group(self.request.user, self.get_object()):
            raise PermissionDenied("Only the group owner or an admin can edit this group.")
        serializer.save()

    def perform_destroy(self, instance):
        # Archive rather than delete: tasks/ideas/links keep their history.
        if not can_manage_group(self.request.user, instance):
            raise PermissionDenied("Only the group owner or an admin can archive this group.")
        instance.active = False
        instance.save(update_fields=["active"])

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        group = self.get_object()
        if not can_manage_group(request.user, group):
            raise PermissionDenied("Only the group owner or an admin can add members.")
        user = User.objects.filter(pk=request.data.get("user"), is_active=True).first()
        if not user:
            raise ValidationError({"user": "Unknown or inactive user."})
        group.members.add(user)
        return Response(GroupSerializer(group, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        group = self.get_object()
        if not can_manage_group(request.user, group):
            raise PermissionDenied("Only the group owner or an admin can remove members.")
        group.members.remove(request.data.get("user"))
        return Response(GroupSerializer(group, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        group = self.get_object()
        now = timezone.now()
        rows = list(group.tasks.values("status", "due_at"))
        open_rows = [t for t in rows if t["status"] != TaskStatus.DONE]
        tiles = {
            "total": len(rows),
            "pending": sum(1 for t in rows if t["status"] == TaskStatus.OPEN),
            "in_progress": sum(1 for t in rows if t["status"] == TaskStatus.IN_PROGRESS),
            "completed": len(rows) - len(open_rows),
            "overdue": sum(1 for t in open_rows if t["due_at"] and t["due_at"] < now),
            "members": group.members.count(),
        }
        activity = [
            {"text": a.text, "task_title": a.task.title,
             "actor": (a.actor.get_full_name() or a.actor.username) if a.actor else "System",
             "created_at": a.created_at}
            for a in TaskActivity.objects.select_related("task", "actor")
            .filter(task__group=group)[:10]
        ]
        return Response({
            "tiles": tiles,
            "members": UserBriefSerializer(group.members.all(), many=True).data,
            "recent_activity": activity,
        })


class NoticeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NoticeSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def _is_manager(self):
        from accounts.permissions import has_capability
        return has_capability(self.request.user, "settings.manage")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["read_ids"] = set(
            NoticeRead.objects.filter(user=self.request.user).values_list("notice_id", flat=True)
        )
        return ctx

    def get_queryset(self):
        # manage=true -> the admin management listing (all statuses)
        if self.request.query_params.get("manage") == "true":
            if not self._is_manager():
                raise PermissionDenied("Notice management is admin-only.")
            return Notice.objects.select_related("author").all()
        return Notice.objects.none()  # list() below builds the user feed

    def list(self, request, *args, **kwargs):
        if request.query_params.get("manage") == "true":
            qs = self.get_queryset()
        else:
            qs = notices_for(request.user)
        p = request.query_params
        read_ids = set(NoticeRead.objects.filter(user=request.user).values_list("notice_id", flat=True))
        if p.get("read") == "true":
            qs = [n for n in qs if n.id in read_ids]
        elif p.get("read") == "false":
            qs = [n for n in qs if n.id not in read_ids]
        if p.get("search"):
            s = p["search"].lower()
            qs = [n for n in qs if s in n.title.lower() or s in n.content.lower()]
        ser = NoticeSerializer(qs, many=True, context={**self.get_serializer_context()})
        return Response(ser.data)

    def retrieve(self, request, *args, **kwargs):
        notice = Notice.objects.filter(pk=kwargs["pk"]).first()
        if not notice:
            return Response(status=404)
        if not self._is_manager() and not (notice.is_live and notice_targets(notice, request.user)):
            raise PermissionDenied("This notice is not available to you.")
        return Response(NoticeSerializer(notice, context=self.get_serializer_context()).data)

    def perform_create(self, serializer):
        if not self._is_manager():
            raise PermissionDenied("Only an admin can create notices.")
        serializer.save(author=self.request.user)

    def perform_update(self, serializer):
        if not self._is_manager():
            raise PermissionDenied("Only an admin can edit notices.")
        serializer.save()

    def perform_destroy(self, instance):
        if not self._is_manager():
            raise PermissionDenied("Only an admin can delete notices.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        if not self._is_manager():
            raise PermissionDenied("Only an admin can publish notices.")
        notice = Notice.objects.get(pk=pk)
        notice.status = NoticeStatus.PUBLISHED
        if not notice.publish_at:
            notice.publish_at = timezone.now()
        notice.save(update_fields=["status", "publish_at"])
        return Response(NoticeSerializer(notice, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        if not self._is_manager():
            raise PermissionDenied("Only an admin can archive notices.")
        notice = Notice.objects.get(pk=pk)
        notice.status = NoticeStatus.ARCHIVED
        notice.save(update_fields=["status"])
        return Response(NoticeSerializer(notice, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notice = Notice.objects.filter(pk=pk).first()
        if not notice or not (notice.is_live and notice_targets(notice, request.user)):
            raise PermissionDenied("This notice is not available to you.")
        NoticeRead.objects.get_or_create(notice=notice, user=request.user)
        return Response({"read": True})


class LinkCollectionViewSet(viewsets.ModelViewSet):
    serializer_class = LinkCollectionSerializer
    queryset = LinkCollection.objects.all()
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("tasks.assign")()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class LinkViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LinkSerializer
    pagination_class = None

    def get_queryset(self):
        qs = visible_links(self.request.user)
        p = self.request.query_params
        if p.get("collection"):
            qs = qs.filter(collection_id=p["collection"])
        if p.get("group"):
            qs = qs.filter(group_id=p["group"])
        if p.get("favorites") == "true":
            qs = qs.filter(favorites=self.request.user)
        if p.get("search"):
            s = p["search"]
            from django.db.models import Q
            qs = qs.filter(Q(title__icontains=s) | Q(url__icontains=s) | Q(description__icontains=s))
        return qs

    def _check_group(self, serializer):
        group = serializer.validated_data.get("group")
        if group and group.id not in user_group_ids(self.request.user) \
                and not can_edit_link(self.request.user, Link(added_by=self.request.user)):
            raise PermissionDenied("You can only scope links to your own groups.")

    def perform_create(self, serializer):
        group = serializer.validated_data.get("group")
        if group and group.id not in user_group_ids(self.request.user):
            from .access import is_workspace_admin
            if not is_workspace_admin(self.request.user):
                raise PermissionDenied("You can only scope links to your own groups.")
        serializer.save(added_by=self.request.user)

    def perform_update(self, serializer):
        if not can_edit_link(self.request.user, self.get_object()):
            raise PermissionDenied("You can only edit links you added.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_edit_link(self.request.user, instance):
            raise PermissionDenied("You can only delete links you added.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def favorite(self, request, pk=None):
        link = self.get_object()
        if link.favorites.filter(pk=request.user.pk).exists():
            link.favorites.remove(request.user)
            return Response({"favorited": False})
        link.favorites.add(request.user)
        return Response({"favorited": True})


class IdeaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = IdeaSerializer

    def get_queryset(self):
        user = self.request.user
        qs = visible_ideas(user)
        p = self.request.query_params
        scope = p.get("scope")
        if scope == "my":
            qs = qs.filter(author=user)
        elif scope == "shared":
            qs = qs.filter(group__isnull=True)
        elif scope == "group":
            qs = qs.filter(group__isnull=False)
        if p.get("group"):
            qs = qs.filter(group_id=p["group"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("search"):
            qs = qs.filter(title__icontains=p["search"])
        return qs

    def perform_create(self, serializer):
        group = serializer.validated_data.get("group")
        if group and group.id not in user_group_ids(self.request.user):
            from .access import is_workspace_admin
            if not is_workspace_admin(self.request.user):
                raise PermissionDenied("You can only post ideas to your own groups.")
        serializer.save(author=self.request.user, status="new")

    def perform_update(self, serializer):
        idea = self.get_object()
        user = self.request.user
        wants_status = serializer.validated_data.get("status", idea.status)
        if wants_status != idea.status and not can_review_ideas(user):
            raise PermissionDenied("Only managers/admin can change idea status.")
        content_fields = {"title", "description", "category", "priority", "group"}
        changing_content = any(
            f in serializer.validated_data and serializer.validated_data[f] != getattr(idea, f)
            for f in content_fields
        )
        if changing_content and idea.author_id != user.id and not can_review_ideas(user):
            raise PermissionDenied("You can only edit your own ideas.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if instance.author_id != user.id and not can_review_ideas(user):
            raise PermissionDenied("You can only delete your own ideas.")
        instance.delete()

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        idea = self.get_object()
        if request.method == "GET":
            return Response(IdeaCommentSerializer(idea.comments.select_related("author"), many=True).data)
        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "Comment cannot be empty."})
        c = IdeaComment.objects.create(idea=idea, author=request.user, body=body[:2000])
        return Response(IdeaCommentSerializer(c).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def vote(self, request, pk=None):
        idea = self.get_object()
        if idea.votes.filter(pk=request.user.pk).exists():
            idea.votes.remove(request.user)
            return Response({"voted": False, "vote_count": idea.votes.count()})
        idea.votes.add(request.user)
        return Response({"voted": True, "vote_count": idea.votes.count()})
