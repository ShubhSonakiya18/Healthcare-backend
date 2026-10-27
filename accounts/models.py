"""The project's user model: email login and a single name field."""

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    """A person using the API. Logs in with an email address, not a username.

    Everything else comes from AbstractUser unchanged: password hashing,
    is_active, is_staff, is_superuser, groups and permissions, date_joined
    and last_login.
    """

    # Remove the AbstractUser fields this project doesn't use.
    username = None
    first_name = None
    last_name = None

    # Stored trimmed and lower-case (see UserManager and RegisterSerializer).
    # unique=True also gives PostgreSQL a unique index on the column.
    email = models.EmailField("email address", unique=True)
    name = models.CharField(max_length=150)

    # Log in with email; `createsuperuser` also asks for a name.
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    # Inheriting AbstractUser.Meta keeps its verbose names; like every model
    # here, User gets an explicit ordering so lists come back in a stable order.
    class Meta(AbstractUser.Meta):
        ordering = ["id"]

    def __str__(self):
        return self.email

    # AbstractUser builds these from first_name and last_name, which no
    # longer exist, so return the single name field instead.
    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name
