from django.urls import path
from . import views

urlpatterns = [
    path('raise/', views.raise_complaint, name='raise_complaint'),
    path('status/', views.user_complaint_status, name='user_complaint_status'),
    path('admin/list/', views.admin_complaint_list, name='admin_complaint_list'),
    path('admin/<int:complaint_id>/resolve/', views.admin_resolve_complaint, name='admin_resolve_complaint'),
]
