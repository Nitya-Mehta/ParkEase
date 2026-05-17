from django.urls import path
from . import views

urlpatterns = [
    path('admin/slots/', views.admin_slot_list, name='admin_slot_list'),
    path('admin/gate-scan/', views.admin_vehicle_scan, name='admin_vehicle_scan'),
    path('admin/exit-payment/<int:assignment_id>/', views.admin_exit_payment, name='admin_exit_payment'),
    path('admin/exit-payment/<int:assignment_id>/verify/', views.verify_exit_payment, name='verify_exit_payment'),
    path('admin/slots/create/', views.admin_slot_create, name='admin_slot_create'),
    path('admin/slots/<int:slot_id>/edit/', views.admin_slot_edit, name='admin_slot_edit'),
    path('admin/slots/<int:slot_id>/toggle/', views.admin_slot_toggle_active, name='admin_slot_toggle_active'),
    path('admin/slots/<int:slot_id>/delete/', views.admin_slot_delete, name='admin_slot_delete'),
    path('admin/slots/<int:slot_id>/force-release/', views.admin_slot_force_release, name='admin_slot_force_release'),
    
    # User paths
    path('request/submit/', views.submit_parking_request, name='submit_parking_request'),
    path('live-status/', views.live_slot_status, name='live_slot_status'),
    path('request/confirm/<int:slot_id>/', views.confirm_parking_request, name='confirm_parking_request'),
    path('request/status/', views.request_status, name='request_status'),
    path('request/auto-book/<int:rule_id>/toggle/', views.toggle_auto_booking_rule, name='toggle_auto_booking_rule'),
    path('request/auto-book/<int:rule_id>/delete/', views.delete_auto_booking_rule, name='delete_auto_booking_rule'),
    path('request/<int:req_id>/cancel/', views.cancel_parking_request, name='cancel_parking_request'),
    path('request/release/', views.user_release_assignment, name='user_release_assignment'),
    
    # Admin Assignment paths
    path('admin/requests/pending/', views.admin_pending_requests, name='admin_pending_requests'),
    path('admin/requests/<int:req_id>/assign/', views.admin_assign_slot, name='admin_assign_slot'),
    path('admin/assignments/active/', views.admin_active_assignments, name='admin_active_assignments'),
    path('admin/assignments/<int:assignment_id>/release/', views.admin_release_assignment, name='admin_release_assignment'),
    path('admin/assignments/validate/<str:token>/', views.admin_validate_assignment_qr, name='admin_validate_assignment_qr'),
]
