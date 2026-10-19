from django.contrib.auth.views import PasswordChangeView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path(
        "password/",
        PasswordChangeView.as_view(
            template_name="password_change.html",
            success_url="/settings/",
        ),
        name="password_change",
    ),
]
