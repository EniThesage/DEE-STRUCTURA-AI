from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import OCCUPATION_CHOICES, User


class SignupForm(UserCreationForm):
    name = forms.CharField(max_length=150)
    email = forms.EmailField()
    occupation = forms.ChoiceField(choices=OCCUPATION_CHOICES)

    class Meta:
        model = User
        fields = ['name', 'email', 'occupation', 'password1', 'password2']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.name = self.cleaned_data['name']
        user.occupation = self.cleaned_data['occupation']
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label='Email')
