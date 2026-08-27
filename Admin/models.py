from django.db import models

# Create your models here.
from django.db import models


class Customer(models.Model):

    CUSTOMER_TYPE_CHOICES = [
        ("regular", "Regular"),
        ("wholesale", "Wholesale"),
        ("new_customer", "New Customer"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    customer_name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=200)

    contact_person = models.CharField(
        max_length=150,
        blank=True,
        null=True
    )

    phone = models.CharField(max_length=15)

    email = models.EmailField(
        blank=True,
        null=True
    )

    gst_number = models.CharField(
        max_length=15,
        blank=True,
        null=True
    )

    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPE_CHOICES,
        default="regular"
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="active"
    )

    address = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.customer_name