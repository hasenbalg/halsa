"""Per-user language activation (issue #10).

LocaleMiddleware resolves the language from session/cookie/Accept-Language.
This middleware runs after authentication and overrides that with the
user's pinned profile language, if any. Empty profile language means
"auto": whatever the browser negotiated stays in effect.
"""

from django.utils import translation


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            try:
                lang = user.profile.language
            except Exception:
                lang = ""
            if lang:
                translation.activate(lang)
        return self.get_response(request)
