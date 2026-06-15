from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

from config.views import api_root

urlpatterns = [
    path("", api_root),
    path("admin/", admin.site.urls),
    path("api/auth/token/", obtain_auth_token),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.history.urls")),
    path("api/kyc/", include("apps.kyc.urls")),
    path("api/admin/blacklist/", include("apps.blacklist.urls")),
    path("api/payments/", include("apps.payments.urls")),
    path("api/p2p/", include("apps.p2p.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
