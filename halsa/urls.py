from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def _admin_login(request):
    """All authentication goes through the 2FA-aware login view."""
    return redirect(f"/accounts/login/?next=/admin/")


# admin.site.urls binds self.login at import time, so patching the
# instance attribute before including it takes effect.
admin.site.login = _admin_login
admin.site.site_header = "Hälsa admin"
admin.site.site_title = "Hälsa"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("tracker.auth_urls")),
    path("", include("tracker.urls")),
]
