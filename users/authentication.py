from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import TokenAuthentication


class BearerTokenAuthentication(TokenAuthentication):
    """Authenticate existing DRF database tokens with a Bearer header."""

    keyword = 'Bearer'


class BearerTokenScheme(OpenApiAuthenticationExtension):
    target_class = 'users.authentication.BearerTokenAuthentication'
    name = 'bearerAuth'
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'description': 'Paste the token returned by /api/users/login/. Swagger adds Bearer automatically.',
        }
