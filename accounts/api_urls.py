from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import api_views

urlpatterns = [
    path('login/', api_views.LoginAPIView.as_view()),
    path('refresh/', TokenRefreshView.as_view()),
    path('logout/', api_views.LogoutAPIView.as_view()),
    path('register/', api_views.RegisterAPIView.as_view()),
    path('me/', api_views.MeAPIView.as_view()),
]
