from urllib.parse import urlparse

from rest_framework import serializers

from accounts.models import User
from crm.serializers import UserBriefSerializer

from .models import Group, Idea, IdeaComment, Link, LinkCollection, Notice


class GroupSerializer(serializers.ModelSerializer):
    owner_detail = UserBriefSerializer(source="owner", read_only=True)
    members_detail = UserBriefSerializer(source="members", many=True, read_only=True)
    member_count = serializers.IntegerField(source="members.count", read_only=True)
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ["id", "name", "description", "category", "owner", "owner_detail",
                  "members", "members_detail", "member_count", "active",
                  "can_manage", "created_at"]
        extra_kwargs = {"members": {"required": False}}

    def get_can_manage(self, obj):
        from .access import can_manage_group
        request = self.context.get("request")
        return bool(request and can_manage_group(request.user, obj))


class NoticeSerializer(serializers.ModelSerializer):
    author_detail = UserBriefSerializer(source="author", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    audience_display = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)
    read = serializers.SerializerMethodField()

    class Meta:
        model = Notice
        fields = ["id", "title", "content", "category", "priority", "priority_display",
                  "status", "status_display", "publish_at", "expire_at",
                  "attachment", "attachment_url", "audience_type", "audience_value",
                  "audience_display", "author_detail", "is_expired", "read",
                  "created_at", "updated_at"]
        extra_kwargs = {"attachment": {"write_only": True, "required": False}}

    def get_attachment_url(self, obj):
        return obj.attachment.url if obj.attachment else None

    def get_read(self, obj):
        read_ids = self.context.get("read_ids")
        if read_ids is None:
            return None
        return obj.id in read_ids

    def get_audience_display(self, obj):
        t, v = obj.audience_type, obj.audience_value or {}
        if t == "everyone":
            return "Everyone"
        if t == "role":
            return f"Role: {v.get('role', '?')}"
        if t == "department":
            return f"Department: {v.get('department', '?')}"
        if t == "group":
            g = Group.objects.filter(pk=v.get("group")).first()
            return f"Group: {g.name if g else '?'}"
        if t == "users":
            return f"{len(v.get('users') or [])} selected user(s)"
        return t

    def validate(self, attrs):
        t = attrs.get("audience_type", getattr(self.instance, "audience_type", "everyone"))
        v = attrs.get("audience_value", getattr(self.instance, "audience_value", {}) or {})
        if t == "role" and not v.get("role"):
            raise serializers.ValidationError({"audience_value": "Pick a role."})
        if t == "department" and not v.get("department"):
            raise serializers.ValidationError({"audience_value": "Pick a department."})
        if t == "group" and not Group.objects.filter(pk=v.get("group")).exists():
            raise serializers.ValidationError({"audience_value": "Pick a valid group."})
        if t == "users":
            ids = v.get("users") or []
            if not ids or not isinstance(ids, list):
                raise serializers.ValidationError({"audience_value": "Pick at least one user."})
            known = set(User.objects.filter(pk__in=ids).values_list("pk", flat=True))
            if set(ids) - known:
                raise serializers.ValidationError({"audience_value": "Unknown user ids."})
        return attrs


class LinkCollectionSerializer(serializers.ModelSerializer):
    link_count = serializers.IntegerField(source="links.count", read_only=True)

    class Meta:
        model = LinkCollection
        fields = ["id", "name", "link_count", "created_at"]


class LinkSerializer(serializers.ModelSerializer):
    added_by_detail = UserBriefSerializer(source="added_by", read_only=True)
    collection_name = serializers.CharField(source="collection.name", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True, default=None)
    favorited = serializers.SerializerMethodField()

    class Meta:
        model = Link
        fields = ["id", "collection", "collection_name", "title", "url", "description",
                  "group", "group_name", "added_by_detail", "favorited", "created_at"]

    def get_favorited(self, obj):
        request = self.context.get("request")
        return bool(request and obj.favorites.filter(pk=request.user.pk).exists())

    def validate_url(self, value):
        scheme = urlparse(value).scheme.lower()
        if scheme not in ("http", "https"):
            raise serializers.ValidationError("Only http/https URLs are allowed.")
        return value


class IdeaCommentSerializer(serializers.ModelSerializer):
    author = UserBriefSerializer(read_only=True)

    class Meta:
        model = IdeaComment
        fields = ["id", "author", "body", "created_at"]


class IdeaSerializer(serializers.ModelSerializer):
    author_detail = UserBriefSerializer(source="author", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    vote_count = serializers.IntegerField(source="votes.count", read_only=True)
    comment_count = serializers.IntegerField(source="comments.count", read_only=True)
    voted = serializers.SerializerMethodField()

    class Meta:
        model = Idea
        fields = ["id", "title", "description", "category", "author_detail",
                  "group", "group_name", "status", "status_display", "priority",
                  "vote_count", "comment_count", "voted", "created_at", "updated_at"]

    def get_voted(self, obj):
        request = self.context.get("request")
        return bool(request and obj.votes.filter(pk=request.user.pk).exists())
