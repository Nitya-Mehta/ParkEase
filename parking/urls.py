from django.urls import path
from . import views

urlpatterns = [
    path('admin/slots/', views.admin_slot_list, name='admin_slot_list'),
    path('admin/slots/create/', views.admin_slot_create, name='admin_slot_create'),
    path('admin/slots/<int:slot_id>/edit/', views.admin_slot_edit, name='admin_slot_edit'),
    path('admin/slots/<int:slot_id>/toggle/', views.admin_slot_toggle_active, name='admin_slot_toggle_active'),
    path('admin/slots/<int:slot_id>/force-release/', views.admin_slot_force_release, name='admin_slot_force_release'),
    
    # User paths
    path('request/submit/', views.submit_parking_request, name='submit_parking_request'),
    path('request/status/', views.request_status, name='request_status'),
    path('request/release/', views.user_release_assignment, name='user_release_assignment'),
    
    # Admin Assignment paths
    path('admin/requests/pending/', views.admin_pending_requests, name='admin_pending_requests'),
    path('admin/requests/<int:req_id>/assign/', views.admin_assign_slot, name='admin_assign_slot'),
    path('admin/assignments/active/', views.admin_active_assignments, name='admin_active_assignments'),
    path('admin/assignments/<int:assignment_id>/release/', views.admin_release_assignment, name='admin_release_assignment'),
]
