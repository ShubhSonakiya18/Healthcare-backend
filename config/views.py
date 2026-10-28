"""JSON error responses for errors that Django, not DRF, answers.

DRF already answers errors inside API views with JSON. These handlers cover
the rest: a URL that matches no route, a request Django rejects as suspicious
(such as a body over DATA_UPLOAD_MAX_MEMORY_SIZE), and unexpected exceptions.
Django uses them only when DEBUG is off; with DEBUG on it shows its detailed
debug pages instead. The bodies follow the API's usual {"detail": ...} shape.
"""

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse


def bad_request(request, exception):
    """handler400, for any client: 400 JSON, naming the size limit when that was the cause."""
    if isinstance(exception, RequestDataTooBig):
        return JsonResponse({"detail": "Request body is too large."}, status=400)
    return JsonResponse({"detail": "Bad request."}, status=400)


def not_found(request, exception):
    """handler404, for any client: 404 JSON for a URL that matches no route."""
    return JsonResponse({"detail": "Not found."}, status=404)


def server_error(request):
    """handler500, for any client: 500 JSON with a generic message."""
    # Deliberately generic: the traceback goes to the server log (LOGGING in
    # settings.py), never to the client.
    return JsonResponse({"detail": "A server error occurred."}, status=500)
