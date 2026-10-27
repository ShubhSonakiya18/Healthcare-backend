"""The manager that creates users and superusers."""

from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Creates users from an email address instead of a username.

    Every user goes through here, so this is where the email is normalised
    and the password is hashed: the plain password never reaches the database.
    """

    # Lets migrations use this manager (for example in data migrations).
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        """Trim and lower-case the whole address.

        Django's version only lower-cases the domain part. Lower-casing all of
        it makes Asha@Example.com and asha@example.com the same account.
        """
        return (email or "").strip().lower()

    def get_by_natural_key(self, email):
        # Used by Django's login check (so also admin login) and by
        # `createsuperuser` to see whether an email is already taken.
        # Normalising here makes every lookup match what create_user stored.
        return super().get_by_natural_key(self.normalize_email(email))

    def _create_user(self, email, password, **extra_fields):
        email = self.normalize_email(email)
        if not email:
            raise ValueError("Users must have an email address.")

        name = (extra_fields.pop("name", None) or "").strip()
        if not name:
            raise ValueError("Users must have a name.")

        user = self.model(email=email, name=name, **extra_fields)
        # set_password() stores a salted hash. A password of None gives an
        # unusable password, so the account can't log in until one is set.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create a normal user: not staff, not superuser."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Create an admin user. Used by `python manage.py createsuperuser`."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)
