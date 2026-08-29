from django.db.models.functions import Lower
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from rest_framework.exceptions import PermissionDenied

from .models import DepartmentOption, Role, User
from .permissions import HasCapability
from .serializers import ChangePasswordSerializer, UserSerializer, UserWriteSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def departments(request):
    """The department dropdown, read by every form. Admin (settings.manage)
    can add one; renaming/deactivating is a PATCH on /departments/<code>."""
    from .permissions import has_capability
    if request.method == "POST":
        if not has_capability(request.user, "settings.manage"):
            raise PermissionDenied("Only an admin can add a department.")
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"name": "Give the department a name."}, status=400)
        code = slugify(str(request.data.get("code") or name))[:20]
        if not code:
            return Response({"code": "Could not build a code from that name."}, status=400)
        if DepartmentOption.objects.filter(code=code).exists():
            return Response({"code": f"'{code}' already exists."}, status=400)
        row = DepartmentOption.objects.create(code=code, name=name[:60])
        return Response({"code": row.code, "name": row.name, "active": row.active},
                        status=status.HTTP_201_CREATED)
    rows = DepartmentOption.objects.filter(active=True)
    if not rows.exists():                       # first boot, before the seed
        from .models import Department
        return Response([{"code": c, "name": n, "active": True} for c, n in Department.choices])
    return Response([{"code": d.code, "name": d.name, "active": d.active} for d in rows])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def department_detail(request, code):
    """Rename (PATCH {name}) or hide (DELETE) one department. Hiding keeps
    every user/task/lead already filed under it -- it only leaves the list."""
    from .permissions import has_capability
    if not has_capability(request.user, "settings.manage"):
        raise PermissionDenied("Only an admin can change departments.")
    row = DepartmentOption.objects.filter(code=code).first()
    if not row:
        return Response({"detail": "Unknown department."}, status=404)
    if request.method == "DELETE":
        in_use = User.objects.filter(department=code, is_active=True).count()
        if in_use:
            return Response(
                {"detail": f"{in_use} active user(s) are still in this department — "
                           "move them first."}, status=400)
        row.active = False
        row.save(update_fields=["active"])
        return Response({"code": row.code, "active": False})
    name = str(request.data.get("name", "")).strip()
    if not name:
        return Response({"name": "Give the department a name."}, status=400)
    row.name = name[:60]
    row.save(update_fields=["name"])
    return Response({"code": row.code, "name": row.name, "active": row.active})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_directory(request):
    """Read-only "My Team" directory, scoped by who you are:
    - users.manage (Admin, HR Manager): the whole company
    - a manager: ONLY the employees who report directly to them
    - everyone else: their own department
    Management actions stay in UserViewSet (users.manage)."""
    from .permissions import has_capability
    viewer = request.user
    users = User.objects.filter(is_active=True).select_related("reporting_manager")
    if has_capability(viewer, "users.manage"):
        pass                                            # whole company
    elif viewer.role == Role.SALES_MANAGER or users.filter(reporting_manager=viewer).exists():
        users = users.filter(reporting_manager=viewer)  # direct reports only
    else:
        users = users.filter(department=viewer.department)
    users = users.order_by(Lower("first_name"), Lower("username"))
    return Response([
        {
            "id": u.id,
            "name": u.get_full_name() or u.username,
            "username": u.username,
            "email": u.email,
            "mobile": u.whatsapp_phone,
            "role": u.role,
            "role_display": u.get_role_display(),
            "department_display": u.get_department_display(),
            "reports_to": (u.reporting_manager.get_full_name() or u.reporting_manager.username)
                          if u.reporting_manager else None,
        }
        for u in users
    ])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    ser = ChangePasswordSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    if not request.user.check_password(ser.validated_data["current_password"]):
        return Response({"detail": "Current password is incorrect."}, status=400)
    request.user.set_password(ser.validated_data["new_password"])
    request.user.save()
    return Response({"detail": "Password changed."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    """Blacklist the presented refresh token."""
    try:
        RefreshToken(request.data.get("refresh")).blacklist()
    except Exception:
        pass  # already invalid/expired -- logout is still fine
    return Response({"detail": "Logged out."})


class UserViewSet(viewsets.ModelViewSet):
    """User management for roles with `users.manage` (Admin, HR Manager).
    Deactivation instead of deletion keeps lead/task history intact."""
    queryset = User.objects.all().order_by(Lower("first_name"), Lower("username"))
    permission_classes = [HasCapability.of("users.manage")]

    def _guard_role(self, requested_role, target=None):
        """Only a full Admin may grant the Admin role or edit another admin --
        stops an HR Manager from escalating anyone (including themselves)."""
        if self.request.user.role == Role.ADMIN:
            return
        if requested_role == Role.ADMIN:
            raise PermissionDenied("Only an Admin can grant the Admin role.")
        if target is not None and target.role == Role.ADMIN:
            raise PermissionDenied("Only an Admin can edit an Admin account.")
        if target is not None and target.pk == self.request.user.pk and requested_role:
            raise PermissionDenied("You cannot change your own role.")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        # Authority first, then input: checking the role AFTER validation let
        # a missing field mask a 403 as a 400.
        self._guard_role(request.data.get("role"))
        write = self.get_serializer(data=request.data)
        write.is_valid(raise_exception=True)
        user = write.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        target = self.get_object()
        self._guard_role(request.data.get("role"), target)
        write = self.get_serializer(target, data=request.data, partial=partial)
        write.is_valid(raise_exception=True)
        user = write.save()
        return Response(UserSerializer(user).data)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Users are never deleted; deactivate instead (POST /deactivate)."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        if user == request.user:
            return Response({"detail": "You cannot deactivate yourself."}, status=400)
        self._guard_role(None, user)
        user.is_active = False
        user.save()
        return Response(UserSerializer(user).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save()
        return Response(UserSerializer(user).data)
