from django.urls import path
from django.views.generic import TemplateView

from routes.views import RoutePlanView

urlpatterns = [
    path('', TemplateView.as_view(template_name='map.html'), name='map'),
    path('api/route/', RoutePlanView.as_view(), name='route-plan'),
]
