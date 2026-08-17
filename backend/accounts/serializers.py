from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User
from .permissions import capabilities_for


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


class UserWriteSerializer(serializers.ModelSerializer):
    """Admin create/update. Password optional on update, required on create."""
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

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

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Password is required for new users."})
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
