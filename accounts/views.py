"""Registration and login endpoints."""

from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import EmailTokenObtainPairSerializer, RegisterSerializer


class RegisterView(CreateAPIView):
    """POST /api/auth/register/ → 201 with {id, name, email}.

    Every other endpoint requires a JWT by default; registration
    deliberately opts out, because a new user has no token yet.
    """

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    # Don't read the Authorization header at all. Otherwise a stale token left
    # in a client (for example Postman's collection auth) would turn a valid
    # registration into a 401. SimpleJWT's own login and refresh views do
    # the same.
    authentication_classes = []


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/ → 200 with {refresh, access}.

    Not Django's own LoginView (that one is for HTML session logins).
    SimpleJWT's token views are already public, and a wrong password, an
    unknown email and an inactive account all get the same 401.
    """

    serializer_class = EmailTokenObtainPairSerializer
