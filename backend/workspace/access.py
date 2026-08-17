"""Visibility & permission helpers for the workspace modules — same pattern
as crm/scoping.py: one small file answers "who can see/do what"."""
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import has_capability

from .models import Group, Idea, Link, Notice, NoticeAudience, NoticeStatus


def is_workspace_admin(user) -> bool:
    return has_capability(user, "tasks.view_all")  # admin


def visible_groups(user):
    qs = Group.objects.prefetch_related("members").select_related("owner")
    if is_workspace_admin(user):
        return qs
    return qs.filter(Q(members=user) | Q(owner=user)).distinct()


def can_create_group(user) -> bool:
    return has_capability(user, "tasks.assign")  # admin + managers


def can_manage_group(user, group: Group) -> bool:
    return is_workspace_admin(user) or group.owner_id == user.id


def user_group_ids(user):
    return set(Group.objects.filter(Q(members=user) | Q(owner=user))
               .values_list("id", flat=True).distinct())


def notice_targets(notice: Notice, user, group_ids=None) -> bool:
    t, v = notice.audience_type, notice.audience_value or {}
    if t == NoticeAudience.EVERYONE:
        return True
    if t == NoticeAudience.ROLE:
        return v.get("role") == user.role
    if t == NoticeAudience.DEPARTMENT:
        return v.get("department") == user.department
    if t == NoticeAudience.GROUP:
        ids = group_ids if group_ids is not None else user_group_ids(user)
        return v.get("group") in ids
    if t == NoticeAudience.USERS:
        return user.id in (v.get("users") or [])
    return False


def live_notices():
    now = timezone.now()
    return (Notice.objects.filter(status=NoticeStatus.PUBLISHED)
            .filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now))
            .filter(Q(expire_at__isnull=True) | Q(expire_at__gt=now)))


def notices_for(user):
    """Live notices targeted at this user (python-side audience filter --
    audiences are tiny JSON blobs, volumes are internal-company scale)."""
    gids = user_group_ids(user)
    return [n for n in live_notices().select_related("author")
            if notice_targets(n, user, gids)]


def visible_links(user):
    qs = Link.objects.select_related("collection", "added_by", "group")
    if is_workspace_admin(user):
        return qs
    return qs.filter(Q(group__isnull=True) | Q(group__members=user) | Q(group__owner=user)).distinct()


def can_edit_link(user, link: Link) -> bool:
    return (is_workspace_admin(user) or has_capability(user, "tasks.assign")
            or link.added_by_id == user.id)


def visible_ideas(user):
    qs = Idea.objects.select_related("author", "group").prefetch_related("votes")
    if is_workspace_admin(user):
        return qs
    return qs.filter(Q(group__isnull=True) | Q(group__members=user)
                     | Q(group__owner=user) | Q(author=user)).distinct()


def can_review_ideas(user) -> bool:
    return has_capability(user, "tasks.assign")  # admin + managers
