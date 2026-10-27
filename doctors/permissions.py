"""Object-level permission for doctors."""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsCreatorOrReadOnly(BasePermission):
    """Anyone logged in may read a doctor; only the user who added it may change or delete it.

    A doctor whose creator was deleted has `created_by = NULL`, which never
    matches a user, so it becomes read-only for everyone through the API.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.created_by_id == request.user.id
