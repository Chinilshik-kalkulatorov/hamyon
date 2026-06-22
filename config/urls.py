from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.authtoken.views import obtain_auth_token

from config.demo import DemoLastOTP
from config.views import api_root

urlpatterns = [
    # Demo deployment: the wallet UI is served at the root so reviewers see a
    # working app. (The public GitHub repo is backend-only; this lives on the
    # deploy-with-ui branch.)
    path("", TemplateView.as_view(template_name="index.html")),
    path("about/", TemplateView.as_view(template_name="about.html")),
    path("api/status/", api_root),
    path("admin/", admin.site.urls),
    path("api/auth/token/", obtain_auth_token),
    path("api/", include("apps.users.urls")),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.history.urls")),
    path("api/kyc/", include("apps.kyc.urls")),
    path("api/admin/blacklist/", include("apps.blacklist.urls")),
    path("api/payments/", include("apps.payments.urls")),
    path("api/p2p/", include("apps.p2p.urls")),
    path("api/demo/last-otp/", DemoLastOTP.as_view()),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
