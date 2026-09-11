from django.db import models
from django.db.models import Sum
from datetime import datetime
from decimal import Decimal

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

    @property
    def performance_score(self):
        from .models import OrderItem, Invoice
        from django.utils import timezone
        from decimal import Decimal
        from django.db.models import Sum

        score = 0
        
        # 1. Purchase Volume (Max 30 points)
        # Cap at 500kg for max points
        total_weight = OrderItem.objects.filter(order__customer=self).aggregate(Sum('weight'))['weight__sum'] or Decimal('0.00')
        volume_points = min(30, (float(total_weight) / 500.0) * 30)
        score += volume_points
        
        # 2. Purchase Frequency (Max 30 points)
        # Cap at 20 orders for max points
        order_count = self.orders.count()
        freq_points = min(30, (order_count / 20.0) * 30)
        score += freq_points
        
        # 3. Payment Clearance & Timing (Max 40 points)
        invoices = Invoice.objects.filter(order__customer=self)
        if not invoices.exists():
            # Neutral payment score for new customers
            score += 40
            return int(max(0, min(100, score)))
            
        total_billed = sum(inv.total_amount for inv in invoices)
        if total_billed == Decimal('0.00'):
            score += 40
            return int(max(0, min(100, score)))
            
        # Total Paid
        total_unpaid = sum(inv.remaining_amount for inv in invoices)
        total_paid = float(total_billed) - float(total_unpaid)
        
        # Ratio points (Max 20 points)
        ratio_points = (total_paid / float(total_billed)) * 20
        score += max(0, min(20, ratio_points))
        
        # Clearance Timing (Max 20 points)
        paid_invoices = [inv for inv in invoices if inv.status == "Paid"]
        if paid_invoices:
            total_days = 0
            count = 0
            for inv in paid_invoices:
                last_payment = inv.payments.order_by('-created_at').first()
                if last_payment:
                    days = (last_payment.created_at - inv.created_at).days
                    total_days += max(0, days)
                    count += 1
            
            if count > 0:
                avg_days = total_days / count
                if avg_days <= 3:
                    score += 20
                elif avg_days <= 7:
                    score += 15
                elif avg_days <= 15:
                    score += 10
                elif avg_days <= 30:
                    score += 5
            else:
                # Fully paid via advances maybe
                score += 20
                
        # Deduct points for severely overdue invoices
        now = timezone.now()
        overdue_invoices = [inv for inv in invoices if inv.status in ["Unpaid", "Partial"]]
        overdue_points = 0
        for inv in overdue_invoices:
            days_unpaid = (now - inv.created_at).days
            if days_unpaid > 30:
                overdue_points += 5
        
        score -= overdue_points
        
        return int(max(0, min(100, score)))

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    def __str__(self):
        return self.name


class CustomerCategoryPrice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='category_prices')
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('customer', 'category')

    def __str__(self):
        return f"{self.customer.customer_name} - {self.category.name} - ₹{self.price}"

class Order(models.Model):

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
    chicken_type = models.CharField(max_length=50, null=True, blank=True)
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    
    # Cutting Team Operational Tracking Fields
    cutting_notes = models.TextField(blank=True, null=True)
    
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


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    chicken_type = models.CharField(max_length=50)
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    price_per_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Cutting Team Category-wise Tracking Fields
    received_quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    waste_quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    meat_delivered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.order.order_number} - {self.chicken_type} - {self.weight}kg"

class DailyPrice(models.Model):
    date = models.DateField()
    chicken_type = models.CharField(max_length=50)
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

    GST_TYPE_CHOICES = [
        ("percentage", "Percentage"),
        ("fixed", "Fixed Amount"),
    ]

    invoice_number = models.CharField(max_length=20, unique=True, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    
    # Legacy fields
    selling_price_per_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # New GST structure
    gst_type = models.CharField(max_length=20, choices=GST_TYPE_CHOICES, default="fixed")
    gst_input = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    calculated_gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

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

    @property
    def total_payments(self):
        return self.payments.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

    @property
    def remaining_amount(self):
        # Quantize just in case to ensure exact 2-decimal precision
        rem = Decimal(str(self.total_amount)) - Decimal(str(self.advance_used)) - Decimal(str(self.total_payments))
        return rem.quantize(Decimal('0.01'))

    def update_status(self):
        rem = self.remaining_amount
        if rem <= Decimal('0.00'):
            self.status = "Paid"
        elif Decimal(str(self.advance_used)) > Decimal('0.00') or self.total_payments > Decimal('0.00'):
            self.status = "Partial"
        else:
            self.status = "Unpaid"
        self.save(update_fields=['status'])


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey(OrderItem, on_delete=models.SET_NULL, null=True, blank=True)
    
    chicken_type_snapshot = models.CharField(max_length=50)
    weight_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price_per_kg_snapshot = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.chicken_type_snapshot}"


class InvoicePayment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ("Cash", "Cash"),
        ("Bank Transfer", "Bank Transfer"),
        ("Cheque", "Cheque"),
        ("UPI", "UPI"),
    ]
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default="Cash")
    reference_no = models.CharField(max_length=100, blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.invoice.invoice_number} - ₹{self.amount}"

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