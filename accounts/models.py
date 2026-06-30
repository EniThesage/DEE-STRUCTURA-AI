from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        return self._create_user(email, password, **extra_fields)


OCCUPATION_CHOICES = [
    ('civil_engineer', 'Civil Engineer'),
    ('quantity_surveyor', 'Quantity Surveyor'),
    ('architect', 'Architect'),
    ('builder_contractor', 'Builder/Contractor'),
    ('site_manager', 'Site Manager'),
    ('other', 'Other'),
]

OCCUPATION_TITLE_ABBREVIATIONS = {
    'civil_engineer': 'Engr.',
    'quantity_surveyor': 'QS',
    'architect': 'Arch.',
    'builder_contractor': 'Builder',
    'site_manager': 'Site Mgr.',
    'other': '',
}


class User(AbstractUser):
    ROLE_CHOICES = [
        ('engineer', 'Engineer'),
        ('admin', 'Admin'),
    ]

    username = None
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='engineer')
    occupation = models.CharField(max_length=30, choices=OCCUPATION_CHOICES, default='civil_engineer')

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.name or self.email

    @property
    def display_title(self):
        abbreviation = OCCUPATION_TITLE_ABBREVIATIONS.get(self.occupation, '')
        label = self.name or self.email
        return f'{abbreviation} {label}'.strip() if abbreviation else label
