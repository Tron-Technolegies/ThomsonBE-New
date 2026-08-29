from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.get_cutting_dashboard, name='cutting_dashboard'),
    path('orders/', views.get_cutting_orders, name='cutting_orders'),
    path('orders/<str:order_number>/status/', views.update_cutting_order_status, name='cutting_update_status'),
    path('notifications/', views.get_cutting_notifications, name='cutting_notifications'),
    path('notifications/mark-read/', views.mark_cutting_notifications_read, name='cutting_notifications_read'),
    path('notifications/clear/', views.clear_cutting_notifications, name='cutting_notifications_clear'),
]