from django.urls import path
from . import views

urlpatterns = [
    # Orders & Pricing
    path('orders/', views.get_purchase_orders, name='accounts_purchase_orders'),
    path('orders/pdf/', views.export_purchase_orders_pdf, name='export_purchase_orders_pdf'),
    path('orders/<int:order_id>/pricing/', views.save_order_pricing, name='accounts_save_order_pricing'),


    # Invoices & Payments
    path('invoices/', views.get_accounts_invoices, name='get_accounts_invoices'),
    path('invoices/create/', views.create_invoice, name='accounts_create_invoice'),
    path('invoices/<str:invoice_id>/pdf/', views.export_invoice_pdf, name='export_invoice_pdf'),
    path('outstanding/', views.get_outstanding_invoices, name='get_outstanding_invoices'),
    path('outstanding/pdf/', views.export_outstanding_pdf, name='export_outstanding_pdf'),
    path('invoices/<int:invoice_id>/payments/', views.get_invoice_payments, name='accounts_get_invoice_payments'),
    path('invoices/<int:invoice_id>/payments/add/', views.add_invoice_payment, name='accounts_add_invoice_payment'),
    
    # Dashboard
    path('dashboard/stats/', views.get_dashboard_stats, name='accounts_dashboard_stats'),
    path('dashboard/charts/', views.get_dashboard_charts, name='accounts_dashboard_charts'),
    path('dashboard/recent-orders/', views.get_recent_orders, name='accounts_recent_orders'),
    
    # Reports
    path('reports/sales/', views.get_sales_report, name='accounts_sales_report'),
    path('reports/sales/pdf/', views.export_sales_report_pdf, name='export_sales_report_pdf'),
    path('reports/customer-purchase/', views.get_customer_purchase_report, name='accounts_customer_purchase'),
    path('reports/daily-prices/', views.get_daily_prices, name='accounts_daily_prices'),
    
    # Advances
    path('advances/', views.get_advances, name='accounts_get_advances'),
    path('advances/pdf/', views.export_advances_pdf, name='export_advances_pdf'),
    path('advances/record/', views.record_advance, name='accounts_record_advance'),
    path('advances/balances/', views.get_advance_balances, name='accounts_advance_balances'),
    path('advances/balances/pdf/', views.export_balances_pdf, name='export_balances_pdf'),
    path('advances/analytics/<int:customer_id>/', views.get_advance_analytics, name='accounts_advance_analytics'),
    
    # Customers
    path('customers/', views.get_accounts_customers, name='accounts_customers'),
]