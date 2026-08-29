from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import DepartmentOption, Role, User
from .permissions import capabilities_for


class FlexibleLoginSerializer(TokenObtainPairSerializer):
    """Sign in with either the username OR the email address -- people
    remember their email far more reliably than a username."""

    def validate(self, attrs):
        login = (attrs.get(self.username_field) or "").strip()
        if "@" in login:
            match = User.objects.filter(email__iexact=login).order_by("id").first()
            if match:
                attrs[self.username_field] = match.username
        return super().validate(attrs)


class UserSerializer(serializers.ModelSerializer):
    """Read serializer -- also what /auth/me returns."""
    capabilities = serializers.SerializerMethodField()
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    department_display = serializers.CharField(source="get_department_display", read_only=True)
    reporting_manager_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "role_display", "department", "department_display",
            "whatsapp_phone", "reporting_manager", "reporting_manager_name",
            "is_active", "date_joined", "last_login", "capabilities",
        ]
        read_only_fields = ["date_joined", "last_login"]

    def get_reporting_manager_name(self, obj):
        m = obj.reporting_manager
        return (m.get_full_name() or m.username) if m else None

    def get_capabilities(self, obj):
        return capabilities_for(obj)


class DepartmentField(serializers.CharField):
    """Accepts any department Admin has added, not just the ones that were
    hard-coded at build time. Blank stays allowed where the model allows it."""

    def to_internal_value(self, data):
        code = super().to_internal_value(data).strip()
        if not code:
            return ""
        valid = {c for c, _ in DepartmentOption.choices_list()}
        if code not in valid:
            raise serializers.ValidationError(
                f"Unknown department '{code}'. Pick one from the list.")
        return code


class UserWriteSerializer(serializers.ModelSerializer):
    """Admin create/update. Password optional on update, required on create."""
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    department = DepartmentField()

    class Meta:
        model = User
        fields = [
            "username", "email", "first_name", "last_name",
            "role", "department", "whatsapp_phone", "reporting_manager",
            "is_active", "password",
        ]

    def validate_password(self, value):
        if value:
            validate_password(value)
        return value

    def _current(self, attrs, field):
        """Value after this save: what was sent, else what is already stored."""
        if field in attrs:
            return attrs[field]
        return getattr(self.instance, field, None) if self.instance else None

    def _checked(self, attrs, field):
        """Creating: always check. Updating: only when the payload touches the
        field. The user form always sends every field, so gaps still get
        forced closed there -- but a one-field PATCH (change a role, fix a
        surname) is not blocked by an unrelated blank."""
        return self.instance is None or field in attrs

    def validate(self, attrs):
        """Every field the system actually depends on is mandatory. A blank
        one does not fail loudly -- it silently drops a notification or sends
        an approval to the wrong person -- so it is rejected at the source."""
        errors = {}
        if self.instance is None and not attrs.get("password"):
            errors["password"] = "Password is required for new users."

        if self._checked(attrs, "email")                 and not str(self._current(attrs, "email") or "").strip():
            errors["email"] = "Email is required — task and approval mails are sent here."

        if self._checked(attrs, "whatsapp_phone"):
            phone = "".join(ch for ch in str(self._current(attrs, "whatsapp_phone") or "")
                            if ch.isdigit())
            if not phone:
                errors["whatsapp_phone"] = (
                    "WhatsApp number is required — without it this person gets "
                    "no WhatsApp alerts.")
            elif len(phone) not in (10, 12):
                errors["whatsapp_phone"] = (
                    "Enter a 10-digit mobile number (or 12 digits with the 91 "
                    "country code).")

        role = self._current(attrs, "role")
        manager = self._current(attrs, "reporting_manager")
        # also demanded when a role CHANGE lands somebody in a post that needs
        # an approver above them
        needs_manager = self._checked(attrs, "reporting_manager") or "role" in attrs
        if needs_manager and role != Role.ADMIN and not manager:
            errors["reporting_manager"] = (
                "Reports to is required — change requests go one step up to "
                "this person. Without it they fall back to the admins.")
        if manager and self.instance and manager.pk == self.instance.pk:
            errors["reporting_manager"] = "Somebody cannot report to themselves."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value
