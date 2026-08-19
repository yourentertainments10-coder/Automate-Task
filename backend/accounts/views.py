from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from rest_framework.exceptions import PermissionDenied

from .models import Role, User
from .permissions import HasCapability
from .serializers import ChangePasswordSerializer, UserSerializer, UserWriteSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


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
    users = users.order_by("first_name", "username")
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
    queryset = User.objects.all().order_by("username")
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
        write = self.get_serializer(data=request.data)
        write.is_valid(raise_exception=True)
        self._guard_role(write.validated_data.get("role"))
        user = write.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        target = self.get_object()
        write = self.get_serializer(target, data=request.data, partial=partial)
        write.is_valid(raise_exception=True)
        self._guard_role(write.validated_data.get("role"), target)
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
