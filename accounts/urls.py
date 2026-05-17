from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('create-admin/', views.create_admin_view, name='create_admin'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.user_dashboard, name='user_dashboard'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('subscriptions/', views.subscriptions_view, name='subscriptions'),
    path('subscriptions/<str:plan_code>/', views.subscription_checkout_view, name='subscription_checkout'),
    path('subscriptions/<str:plan_code>/verify/', views.subscription_verify_view, name='subscription_verify'),
    path('chatbot/', views.chatbot_view, name='chatbot'),
    path('chatbot/ask/', views.chatbot_ask, name='chatbot_ask'),
]
