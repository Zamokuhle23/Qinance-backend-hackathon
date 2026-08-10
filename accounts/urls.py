# accounts/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from .views import RegisterView ,CustomLoginView # our only custom one

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path("login/", CustomLoginView.as_view(), name="login"),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

]
