from django.urls import path
from . import views

urlpatterns = [
    path("customers/add/", views.add_customer, name="add_customer"),
    path("customers/", views.view_all_customers, name="view_all_customers"),
    path("customers/<int:customer_id>/", views.view_single_customer, name="view_single_customer"),
    path("customers/<int:customer_id>/edit/", views.edit_customer, name="edit_customer"),
    path("customers/<int:customer_id>/delete/", views.delete_customer, name="delete_customer"),
]