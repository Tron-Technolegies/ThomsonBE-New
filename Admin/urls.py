from django.urls import path
from . import views

urlpatterns = [
    path("customers/add/", views.add_customer, name="add_customer"),
    path("customers/", views.view_all_customers, name="view_all_customers"),
    path("customers/<int:customer_id>/", views.view_single_customer, name="view_single_customer"),
    path("customers/<int:customer_id>/edit/", views.edit_customer, name="edit_customer"),
    path("customers/<int:customer_id>/delete/", views.delete_customer, name="delete_customer"),
    
    path("customers/<int:customer_id>/prices/", views.get_customer_prices, name="get_customer_prices"),
    path("customers/<int:customer_id>/prices/update/", views.update_customer_prices, name="update_customer_prices"),
    
    path("orders/", views.view_all_orders, name="view_all_orders"),
    path("orders/stats/", views.get_order_stats, name="get_order_stats"),
    path("orders/add/", views.add_order, name="add_order"),
    path("orders/<int:order_id>/edit/", views.edit_order, name="edit_order"),
    path("orders/<int:order_id>/delete/", views.delete_order, name="delete_order"),
    path("orders/<int:order_id>/pricing/", views.save_order_pricing, name="save_order_pricing"),
    
    path("daily-prices/", views.get_daily_prices, name="get_daily_prices"),
    path("daily-prices/update/", views.update_daily_prices, name="update_daily_prices"),
    
    path("categories/", views.get_categories, name="get_categories"),
    path("categories/add/", views.add_category, name="add_category"),
    path("categories/<int:category_id>/delete/", views.delete_category, name="delete_category"),

    path("accounts/orders/", views.get_accounts_orders, name="get_accounts_orders"),
    path("invoices/create/", views.create_invoice, name="create_invoice"),
    path("invoices/", views.get_all_invoices, name="get_all_invoices"),
    path("invoices/<int:invoice_id>/payments/add/", views.add_invoice_payment, name="add_invoice_payment"),
    path("invoices/<int:invoice_id>/payments/", views.get_invoice_payments, name="get_invoice_payments"),

    path("advances/", views.get_advances, name="get_advances"),
    path("advances/record/", views.record_advance, name="record_advance"),
    path("advances/balance/", views.get_advance_balances, name="get_advance_balances"),

    path("dashboard/stats/", views.get_dashboard_stats, name="get_dashboard_stats"),
    path("dashboard/charts/", views.get_dashboard_charts, name="get_dashboard_charts"),
    path("dashboard/recent-orders/", views.get_recent_orders, name="get_recent_orders"),
    
    path("reports/customers/", views.get_customer_purchase_report, name="get_customer_purchase_report"),

    path("notifications/", views.get_notifications, name="get_notifications"),
    path("notifications/read/", views.mark_notifications_read, name="mark_notifications_read"),
    path("notifications/clear/", views.clear_notifications, name="clear_notifications"),
]