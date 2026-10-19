"""Security response headers, emitted by the app itself.

Hälsa ships no reverse proxy: whatever terminates TLS in front of it is
operator territory. Hardening headers that must always travel with the
app's own responses therefore live here. TLS-related policy (HSTS,
redirects) stays config-driven because the app usually sees plain http
behind the proxy.
"""

# The app is zero-JavaScript, so scripts are simply forbidden.
# style-src needs 'unsafe-inline' for the inline style attribute the
# legend swatches use. /admin/ is excluded: Django's own views ship
# inline JS we must not break.
CSP = (
    "default-src 'self'; "
    "script-src 'none'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/admin/"):
            response["Content-Security-Policy"] = CSP
        response.setdefault("Referrer-Policy", "same-origin")
        return response
