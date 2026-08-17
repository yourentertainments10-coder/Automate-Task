from django.contrib import admin

from .models import Group, Idea, IdeaComment, Link, LinkCollection, Notice


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "owner", "active", "created_at")
    list_filter = ("active", "category")


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "priority", "audience_type", "publish_at", "expire_at")
    list_filter = ("status", "priority", "audience_type")


admin.site.register(LinkCollection)
admin.site.register(Link)
admin.site.register(Idea)
admin.site.register(IdeaComment)
