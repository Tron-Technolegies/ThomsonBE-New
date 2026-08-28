from django.db import models
from datetime import datetime

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

class Order(models.Model):
    CHICKEN_TYPE_CHOICES = [
        ("Full Chicken", "Full Chicken"),
        ("Dressed Chicken", "Dressed Chicken"),
        ("Boneless Chicken", "Boneless Chicken"),
    ]

    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Cutting", "Cutting"),
        ("Ready", "Ready"),
        ("Delivered", "Delivered"),
        ("Cancelled", "Cancelled"),
    ]

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders')
    
    delivery_date = models.DateField()
    chicken_type = models.CharField(max_length=50, choices=CHICKEN_TYPE_CHOICES)
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.order_number:
            year = datetime.now().year
            last_order = Order.objects.filter(order_number__startswith=f'ORD-{year}-').order_by('order_number').last()
            if last_order:
                # e.g., ORD-2026-0001
                try:
                    last_number = int(last_order.order_number.split('-')[-1])
                    new_number = last_number + 1
                except ValueError:
                    new_number = 1
            else:
                new_number = 1
            self.order_number = f"ORD-{year}-{new_number:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number


class DailyPrice(models.Model):
    date = models.DateField()
    chicken_type = models.CharField(max_length=50, choices=Order.CHICKEN_TYPE_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('date', 'chicken_type')

    def __str__(self):
        return f"{self.chicken_type} - {self.date} - ₹{self.price}"


class Invoice(models.Model):
    STATUS_CHOICES = [
        ("Unpaid", "Unpaid"),
        ("Partial", "Partial"),
        ("Paid", "Paid"),
    ]

    invoice_number = models.CharField(max_length=20, unique=True, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    
    selling_price_per_kg = models.DecimalField(max_digits=10, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    advance_used = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Unpaid")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            year = datetime.now().year
            last_invoice = Invoice.objects.filter(invoice_number__startswith=f'INV-{year}-').order_by('invoice_number').last()
            if last_invoice:
                try:
                    last_number = int(last_invoice.invoice_number.split('-')[-1])
                    new_number = last_number + 1
                except ValueError:
                    new_number = 1
            else:
                new_number = 1
            self.invoice_number = f"INV-{year}-{new_number:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.invoice_number


class AdvancePayment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ("Cash", "Cash"),
        ("Bank Transfer", "Bank Transfer"),
        ("Cheque", "Cheque"),
        ("UPI", "UPI"),
    ]

    advance_number = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='advances')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default="Cash")
    reference_no = models.CharField(max_length=100, blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.advance_number:
            year = datetime.now().year
            last_adv = AdvancePayment.objects.filter(advance_number__startswith=f'ADV-{year}-').order_by('advance_number').last()
            if last_adv:
                try:
                    last_number = int(last_adv.advance_number.split('-')[-1])
                    new_number = last_number + 1
                except ValueError:
                    new_number = 1
            else:
                new_number = 1
            self.advance_number = f"ADV-{year}-{new_number:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.advance_number


class Notification(models.Model):
    TYPE_CHOICES = [
        ("order", "Order"),
        ("payment", "Payment"),
        ("invoice", "Invoice"),
        ("alert", "Alert"),
    ]

    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title