"""Object-level permission for patients."""

from rest_framework.permissions import BasePermission


class IsPatientOwner(BasePermission):
    """Only the user who created a patient may read, change or delete it.

    A backstop: the views already limit their queryset to the caller's
    patients, so another user's patient is a 404 before this runs. It still
    protects the data if a queryset is ever widened by mistake.
    """

    def has_object_permission(self, request, view, obj):
        return obj.created_by_id == request.user.id
