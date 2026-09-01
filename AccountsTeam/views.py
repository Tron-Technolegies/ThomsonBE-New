from Admin.models import Invoice, Order, OrderItem, InvoiceItem, AdvancePayment, InvoicePayment, Customer, DailyPrice
from django.http import JsonResponse, HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import json
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Count, F
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt

def get_accounts_invoices(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    invoices_qs = Invoice.objects.select_related('order', 'order__customer').prefetch_related('items').order_by('-created_at')
    
    target_date = request.GET.get('date')
    if target_date:
        # Assuming we filter by created_at date
        invoices_qs = invoices_qs.filter(created_at__date=target_date)

    
    # Calculate stats for the KPI cards
    total_invoiced = 0.0
    total_tax = 0.0
    gross_total = 0.0
    amount_paid = 0.0
    cleared_count = 0
    
    data = []
    for i in invoices_qs:
        # Pre-calculated decimal values
        total_amt = float(i.total_amount)
        gst_amt = float(i.calculated_gst_amount)
        adv_used = float(i.advance_used)
        direct_payments = float(i.total_payments)
        remaining = float(i.remaining_amount)
        
        # Add to global stats
        gross_total += total_amt
        total_tax += gst_amt
        total_invoiced += (total_amt - gst_amt)
        amount_paid += (adv_used + direct_payments)
        if remaining <= 0:
            cleared_count += 1
            
        # Serialize items
        items_data = []
        for item in i.items.all():
            items_data.append({
                "id": item.id,
                "chicken_type_snapshot": item.chicken_type_snapshot,
                "weight_snapshot": float(item.weight_snapshot),
                "selling_price_per_kg_snapshot": float(item.selling_price_per_kg_snapshot),
                "subtotal": float(item.weight_snapshot) * float(item.selling_price_per_kg_snapshot)
            })

        data.append({
            "id": i.invoice_number,
            "order_id": i.order.order_number,
            "customer": i.order.customer.customer_name,
            "date": i.created_at.strftime("%d %b %Y"),
            "delivery_date": i.order.delivery_date.strftime("%d %b %Y"),
            "amount": float(i.total_amount - i.calculated_gst_amount),
            "tax": gst_amt,
            "gst_type": i.gst_type,
            "gst_input": float(i.gst_input),
            "total": total_amt,
            "status": i.status,
            "advance": adv_used,
            "balance": remaining,
            "items": items_data
        })
        
    stats = {
        "total_invoiced": total_invoiced,
        "total_tax": total_tax,
        "gross_total": gross_total,
        "amount_paid": amount_paid,
        "cleared_count": cleared_count
    }
        
    return JsonResponse({
        "success": True, 
        "invoices": data,
        "stats": stats
    })


def get_outstanding_invoices(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    # We exclude 'Paid' explicitly
    invoices_qs = Invoice.objects.select_related('order', 'order__customer').exclude(status='Paid').order_by('-created_at')
    
    target_date = request.GET.get('date')
    if target_date:
        invoices_qs = invoices_qs.filter(order__delivery_date=target_date)
    
    total_outstanding = 0.0
    overdue_amount = 0.0
    due_this_week_count = 0
    
    data = []
    for i in invoices_qs:
        rem = float(i.remaining_amount)
        if rem <= 0:
            continue
            
        total_outstanding += rem
        # For this prototype, all unpaid are considered overdue
        overdue_amount += rem
        due_this_week_count += 1

        data.append({
            "id": i.invoice_number,
            "invoice_id": i.id, # needed for payment endpoint route which uses PK
            "customer": i.order.customer.customer_name,
            "amount": float(i.total_amount - i.calculated_gst_amount),
            "tax": float(i.calculated_gst_amount),
            "total": float(i.total_amount),
            "status": i.status,
            "advance": float(i.advance_used),
            "balance": rem,
            "due_date": i.order.delivery_date.strftime("%d %b %Y")
        })
        
    return JsonResponse({
        "success": True, 
        "invoices": data,
        "stats": {
            "total_outstanding": total_outstanding,
            "overdue_amount": overdue_amount,
            "due_this_week_count": due_this_week_count
        }
    })

def get_purchase_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    orders = Order.objects.filter(status__in=['Ready', 'Delivered']).prefetch_related('items', 'customer').order_by('-created_at')

    target_date = request.GET.get('date')
    if target_date:
        orders = orders.filter(delivery_date=target_date)

    order_list = []
    for order in orders:
        items_list = []
        total_weight = 0.0
        
        for oi in order.items.all():
            weight = float(oi.weight) if oi.weight else 0.0
            total_weight += weight
            items_list.append({
                "id": oi.id,
                "chicken_type": oi.chicken_type,
                "weight": str(oi.weight),
                "price_per_kg": float(oi.price_per_kg) if oi.price_per_kg else None
            })

        order_list.append({
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "delivery_date": order.delivery_date.strftime("%d %b %Y"),
            "status": order.status,
            "items": items_list,
            "total_weight": total_weight
        })

    return JsonResponse({
        "success": True, 
        "count": len(order_list),
        "orders": order_list
    })

@csrf_exempt
@transaction.atomic
def create_invoice(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        order_id = data.get("order_id")
        gst_type = data.get("gst_type", "percentage")
        gst_input_raw = data.get("gst_input", 0)

        if not order_id:
            return JsonResponse({"success": False, "message": "Order ID is required."}, status=400)

        # 1. Fetch Order
        try:
            order = Order.objects.select_for_update().get(id=order_id)
        except Order.DoesNotExist:
            return JsonResponse({"success": False, "message": "Order not found."}, status=404)

        # Validate order status
        if order.status not in ["Ready", "Delivered"]:
            return JsonResponse({"success": False, "message": f"Cannot generate invoice for order in {order.status} status."}, status=400)

        # 2. Check for existing invoice
        if hasattr(order, 'invoice'):
            return JsonResponse({"success": False, "message": "Invoice already exists for this order."}, status=400)

        # 3. Validate items and calculate subtotal
        items = order.items.all()
        if not items:
            return JsonResponse({"success": False, "message": "Order has no items."}, status=400)

        subtotal = Decimal('0.00')
        for item in items:
            if item.price_per_kg is None or item.price_per_kg < 0:
                return JsonResponse({"success": False, "message": f"Item {item.chicken_type} missing valid selling price."}, status=400)
            
            weight = Decimal(str(item.weight))
            price = Decimal(str(item.price_per_kg))
            subtotal += (weight * price)

        # 4. Calculate GST
        try:
            gst_input = Decimal(str(gst_input_raw))
        except:
            return JsonResponse({"success": False, "message": "Invalid GST value."}, status=400)

        if gst_type not in ["percentage", "fixed"]:
            return JsonResponse({"success": False, "message": "Invalid GST type."}, status=400)

        if gst_type == "percentage":
            calculated_gst_amount = subtotal * (gst_input / Decimal('100.00'))
        else:
            calculated_gst_amount = gst_input

        # Quantize GST
        calculated_gst_amount = calculated_gst_amount.quantize(Decimal('0.01'))
        
        total_amount = subtotal + calculated_gst_amount

        # 5. Advance Application (with lock on customer advances)
        customer = order.customer
        
        # Calculate total advances
        adv_agg = AdvancePayment.objects.filter(customer=customer).aggregate(Sum('amount'))
        total_advances = adv_agg['amount__sum'] or Decimal('0.00')

        # Calculate total used advances
        inv_agg = Invoice.objects.filter(order__customer=customer).aggregate(Sum('advance_used'))
        total_used = inv_agg['advance_used__sum'] or Decimal('0.00')

        available_advance = total_advances - total_used
        
        advance_used = Decimal('0.00')
        if available_advance > Decimal('0.00'):
            advance_used = min(available_advance, total_amount)

        # 6. Determine Status
        remaining_amount = total_amount - advance_used
        if remaining_amount <= Decimal('0.00'):
            status = "Paid"
        elif advance_used > Decimal('0.00'):
            status = "Partial"
        else:
            status = "Unpaid"

        # 7. Create Invoice
        invoice = Invoice.objects.create(
            order=order,
            gst_type=gst_type,
            gst_input=gst_input,
            calculated_gst_amount=calculated_gst_amount,
            total_amount=total_amount,
            advance_used=advance_used,
            status=status
        )

        # 8. Create InvoiceItems (Snapshot)
        for item in items:
            InvoiceItem.objects.create(
                invoice=invoice,
                order_item=item,
                chicken_type_snapshot=item.chicken_type,
                weight_snapshot=item.weight,
                selling_price_per_kg_snapshot=item.price_per_kg
            )

        return JsonResponse({
            "success": True,
            "message": "Invoice generated successfully.",
            "invoice": {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "order_id": order.id,
                "subtotal": float(subtotal.quantize(Decimal('0.01'))),
                "gst_type": invoice.gst_type,
                "gst_input": float(invoice.gst_input),
                "gst_amount": float(invoice.calculated_gst_amount),
                "total_amount": float(invoice.total_amount),
                "advance_used": float(invoice.advance_used),
                "remaining_amount": float(remaining_amount.quantize(Decimal('0.01'))),
                "status": invoice.status
            }
        })

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)

@csrf_exempt
@transaction.atomic
def add_invoice_payment(request, invoice_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        amount_raw = data.get("amount")
        payment_method = data.get("payment_method", "Cash")
        reference_no = data.get("reference_no", "")
        note = data.get("note", "")

        if amount_raw is None:
            return JsonResponse({"success": False, "message": "Amount is required."}, status=400)

        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal('0.01'))
        except:
            return JsonResponse({"success": False, "message": "Invalid amount format."}, status=400)

        if amount <= Decimal('0.00'):
            return JsonResponse({"success": False, "message": "Payment amount must be greater than 0."}, status=400)

        try:
            invoice = Invoice.objects.select_for_update().get(id=invoice_id)
        except Invoice.DoesNotExist:
            return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)

        current_remaining = invoice.remaining_amount
        if current_remaining <= Decimal('0.00'):
            return JsonResponse({"success": False, "message": "Invoice is already paid in full."}, status=400)

        if amount > current_remaining:
            return JsonResponse({
                "success": False, 
                "message": f"Payment amount (₹{amount}) exceeds remaining balance (₹{current_remaining})."
            }, status=400)

        # Create the payment
        payment = InvoicePayment.objects.create(
            invoice=invoice,
            amount=amount,
            payment_method=payment_method,
            reference_no=reference_no,
            note=note
        )

        # Update the invoice status based on new balance
        invoice.update_status()

        return JsonResponse({
            "success": True,
            "message": "Payment recorded successfully.",
            "payment": {
                "id": payment.id,
                "amount": float(payment.amount),
                "payment_method": payment.payment_method,
                "reference_no": payment.reference_no,
                "note": payment.note,
                "created_at": payment.created_at.strftime("%d %b %Y, %H:%M")
            },
            "new_balance": float(invoice.remaining_amount),
            "new_status": invoice.status
        })

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


def get_invoice_payments(request, invoice_id):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    try:
        invoice = Invoice.objects.get(id=invoice_id)
        payments_qs = invoice.payments.all().order_by('created_at')

        payments_data = []
        for p in payments_qs:
            payments_data.append({
                "id": p.id,
                "amount": float(p.amount),
                "payment_method": p.payment_method,
                "reference_no": p.reference_no,
                "note": p.note,
                "date": p.created_at.strftime("%d %b %Y")
            })

        return JsonResponse({
            "success": True,
            "invoice": {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "total_amount": float(invoice.total_amount),
                "advance_used": float(invoice.advance_used),
                "total_direct_payments": float(invoice.total_payments),
                "remaining_amount": float(invoice.remaining_amount),
                "status": invoice.status
            },
            "payments": payments_data
        })
    except Invoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)

def get_advances(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    advances = AdvancePayment.objects.select_related('customer').order_by('-created_at')
    
    target_date = request.GET.get('date')
    if target_date:
        advances = advances.filter(created_at__date=target_date)

    
    data = []
    for a in advances:
        data.append({
            "id": a.advance_number,
            "customer": a.customer.customer_name,
            "amount": float(a.amount),
            "payment_method": a.payment_method,
            "reference_no": a.reference_no,
            "note": a.note,
            "date": a.created_at.strftime("%d %b %Y, %I:%M %p")
        })

    return JsonResponse({
        "success": True,
        "advances": data
    })

@csrf_exempt
@transaction.atomic
def record_advance(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        customer_id = data.get("customer_id")
        amount_raw = data.get("amount")
        payment_method = data.get("payment_method", "Cash")
        reference_no = data.get("reference_no", "")
        note = data.get("note", "")

        if not customer_id:
            return JsonResponse({"success": False, "message": "Customer is required."}, status=400)

        if amount_raw is None:
            return JsonResponse({"success": False, "message": "Amount is required."}, status=400)

        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal('0.01'))
        except:
            return JsonResponse({"success": False, "message": "Invalid amount format."}, status=400)

        if amount <= Decimal('0.00'):
            return JsonResponse({"success": False, "message": "Advance amount must be greater than 0."}, status=400)

        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

        advance = AdvancePayment.objects.create(
            customer=customer,
            amount=amount,
            payment_method=payment_method,
            reference_no=reference_no,
            note=note
        )

        return JsonResponse({
            "success": True,
            "message": "Advance recorded successfully.",
            "advance": {
                "id": advance.advance_number,
                "customer": customer.customer_name,
                "amount": float(advance.amount)
            }
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)

def get_advance_balances(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    customers = Customer.objects.all()
    
    target_date = request.GET.get('date')
    
    balances = []
    total_advances_all = Decimal('0.00')
    total_used_all = Decimal('0.00')
    available_advance_all = Decimal('0.00')

    for c in customers:
        adv_qs = AdvancePayment.objects.filter(customer=c)
        inv_qs = Invoice.objects.filter(order__customer=c)
        
        if target_date:
            adv_qs = adv_qs.filter(created_at__date__lte=target_date)
            inv_qs = inv_qs.filter(created_at__date__lte=target_date)

        adv_agg = adv_qs.aggregate(Sum('amount'))
        total_advances = adv_agg['amount__sum'] or Decimal('0.00')

        inv_agg = inv_qs.aggregate(Sum('advance_used'))
        total_used = inv_agg['advance_used__sum'] or Decimal('0.00')

        available = total_advances - total_used

        percent = (total_used / total_advances) * Decimal('100.00') if total_advances > 0 else Decimal('0.00')
        percent = percent.quantize(Decimal('0.1'))
        
        last_tx_obj = AdvancePayment.objects.filter(customer=c).order_by('-created_at').first()
        last_tx = last_tx_obj.created_at.strftime("%d %b %Y") if last_tx_obj else "N/A"

        if total_advances > 0:
            balances.append({
                "customer_id": c.id,
                "customer_name": c.customer_name,
                "received": float(total_advances),
                "consumed": float(total_used),
                "balance": float(available),
                "percent": float(percent),
                "last_tx": last_tx
            })
            
            total_advances_all += total_advances
            total_used_all += total_used
            available_advance_all += available

    return JsonResponse({
        "success": True,
        "balances": balances,
        "stats": {
            "total_advances": float(total_advances_all),
            "total_used": float(total_used_all),
            "available_advance": float(available_advance_all)
        }
    })

def get_accounts_customers(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
    
    customers = Customer.objects.filter(status='active').order_by('customer_name')
    data = []
    for c in customers:
        data.append({
            "id": c.id,
            "customer_name": c.customer_name,
            "company_name": c.company_name,
            "phone": c.phone
        })
        
    return JsonResponse({
        "success": True,
        "customers": data
    })

def get_dashboard_stats(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    target_date = request.GET.get('date')
    
    inv_qs = Invoice.objects.all()
    ord_qs = Order.objects.all()
    if target_date:
        inv_qs = inv_qs.filter(created_at__date=target_date)
        ord_qs = ord_qs.filter(created_at__date=target_date)
        
    total_revenue = inv_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_orders = ord_qs.count()
    outstanding = inv_qs.exclude(status='Paid').aggregate(Sum('remaining_amount'))['remaining_amount__sum'] or Decimal('0.00')
    total_customers = Customer.objects.filter(status='active').count()

    return JsonResponse({
        "success": True,
        "revenue": float(total_revenue),
        "orders": total_orders,
        "customers": total_customers,
        "outstanding": float(outstanding)
    })

def get_dashboard_charts(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    target_date = request.GET.get('date')
    
    # 1. Payment Methods (combining InvoicePayment and AdvancePayment)
    pm_qs1 = InvoicePayment.objects.all()
    pm_qs2 = AdvancePayment.objects.all()
    if target_date:
        pm_qs1 = pm_qs1.filter(created_at__date=target_date)
        pm_qs2 = pm_qs2.filter(created_at__date=target_date)
        
    pm_agg1 = pm_qs1.values('payment_method').annotate(total=Sum('amount'))
    pm_agg2 = pm_qs2.values('payment_method').annotate(total=Sum('amount'))
    
    methods_dict = {}
    total_pm = Decimal('0.00')
    
    for item in pm_agg1:
        pm = item['payment_method']
        val = item['total'] or Decimal('0.00')
        methods_dict[pm] = methods_dict.get(pm, Decimal('0.00')) + val
        total_pm += val
        
    for item in pm_agg2:
        pm = item['payment_method']
        val = item['total'] or Decimal('0.00')
        methods_dict[pm] = methods_dict.get(pm, Decimal('0.00')) + val
        total_pm += val
        
    methods_list = []
    for k, v in methods_dict.items():
        percent = (v / total_pm * Decimal('100.00')).quantize(Decimal('0.1')) if total_pm > 0 else Decimal('0.0')
        methods_list.append({
            "name": k,
            "amount": f"₹{float(v):,.2f}",
            "percent": float(percent)
        })
    methods_list.sort(key=lambda x: x['percent'], reverse=True)

    # 2. Revenue Trend (last 7 days of invoices)
    today = timezone.now().date()
    revenue_trend = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%a")
        day_sum = Invoice.objects.filter(created_at__date=day).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
        revenue_trend.append({
            "day": day_str,
            "revenue": float(day_sum)
        })

    # 3. Top Customers
    tc_qs = Invoice.objects.values('order__customer__customer_name').annotate(total=Sum('total_amount')).order_by('-total')[:5]
    top_customers = []
    tc_max = Decimal('0.00')
    for item in tc_qs:
        val = item['total'] or Decimal('0.00')
        if val > tc_max:
            tc_max = val
        top_customers.append({
            "customer": item['order__customer__customer_name'],
            "total": float(val),
            "raw_total": val
        })
        
    # calculate height percent for top customers UI
    for t in top_customers:
        t['percent'] = float((t['raw_total'] / tc_max * Decimal('100.00')).quantize(Decimal('1.0'))) if tc_max > 0 else 0
        del t['raw_total']

    return JsonResponse({
        "success": True,
        "payment_methods": methods_list,
        "revenue_trend": revenue_trend,
        "top_customers": top_customers
    })

def get_recent_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    return JsonResponse({"success": True, "orders": []})  # Not explicitly asked for now, stub it to prevent crashes

def get_advance_analytics(request, customer_id):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)
        
    target_date_str = request.GET.get('date')
    if target_date_str:
        try:
            today = timezone.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except:
            today = timezone.now().date()
    else:
        today = timezone.now().date()
        
    trend = []
    monthly_summary = []
    
    for i in range(6, -1, -1):
        # Approx month math
        month_start = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year+1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month+1)
            
        month_str = month_start.strftime("%b")
        
        adv_qs = AdvancePayment.objects.filter(customer=customer, created_at__lt=next_month_start)
        inv_qs = Invoice.objects.filter(order__customer=customer, created_at__lt=next_month_start)
        
        total_advances = adv_qs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_used = inv_qs.aggregate(Sum('advance_used'))['advance_used__sum'] or Decimal('0.00')
        
        balance = total_advances - total_used
        
        # Monthly transactions IN that month
        inv_month = Invoice.objects.filter(
            order__customer=customer, 
            created_at__gte=month_start, 
            created_at__lt=next_month_start
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')

        trend.append({
            "month": month_str,
            "balance": float(balance),
            "purchase": float(inv_month)
        })
        
        # (moved up)
        monthly_summary.append({
            "month": month_str,
            "purchased": f"₹{float(inv_month):,.2f}",
            "remaining": f"₹{float(balance):,.2f}"
        })
        
    # Reverse summary so newest is top
    monthly_summary.reverse()
    
    return JsonResponse({
        "success": True,
        "trend": trend,
        "monthly_summary": monthly_summary
    })

def get_sales_report(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    target_date_str = request.GET.get('date')
    period = request.GET.get('period', 'Daily') # Daily, Weekly, Monthly
    
    invoices = Invoice.objects.select_related('order', 'order__customer').order_by('-created_at')
    
    if target_date_str:
        try:
            target_date = timezone.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except:
            target_date = timezone.now().date()
    else:
        target_date = timezone.now().date()
        
    if period == 'Daily':
        invoices = invoices.filter(created_at__date=target_date)
    elif period == 'Weekly':
        start_of_week = target_date - timedelta(days=target_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        invoices = invoices.filter(created_at__date__gte=start_of_week, created_at__date__lte=end_of_week)
    elif period == 'Monthly':
        invoices = invoices.filter(created_at__year=target_date.year, created_at__month=target_date.month)
    
    total_revenue = invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_orders = invoices.count()
    
    sales_list = []
    for inv in invoices:
        sales_list.append({
            "invoice_no": inv.invoice_number,
            "customer": inv.order.customer.customer_name,
            "date": inv.created_at.strftime("%d %b %Y, %I:%M %p"),
            "amount": float(inv.total_amount),
            "status": inv.status
        })
        
    revenue_trend = []
    if period == 'Monthly':
        for i in range(5, -1, -1):
            month_start = (target_date.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
            month_str = month_start.strftime("%b")
            rev = Invoice.objects.filter(created_at__year=month_start.year, created_at__month=month_start.month).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
            revenue_trend.append({
                "day": month_str,
                "revenue": float(rev)
            })
    elif period == 'Weekly':
        start_of_week = target_date - timedelta(days=target_date.weekday())
        for i in range(6, -1, -1):
            w_start = start_of_week - timedelta(weeks=i)
            w_end = w_start + timedelta(days=6)
            rev = Invoice.objects.filter(created_at__date__gte=w_start, created_at__date__lte=w_end).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
            revenue_trend.append({
                "day": w_start.strftime("%d %b"),
                "revenue": float(rev)
            })
    else: 
        for i in range(6, -1, -1):
            day = target_date - timedelta(days=i)
            rev = Invoice.objects.filter(created_at__date=day).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
            revenue_trend.append({
                "day": day.strftime("%a"),
                "revenue": float(rev)
            })
            
    return JsonResponse({
        "success": True,
        "sales": sales_list,
        "total_revenue": float(total_revenue),
        "total_orders": total_orders,
        "revenue_trend": revenue_trend
    })

def get_customer_purchase_report(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
    # Just basic wrapper in case frontend still hits it for old analytics UI
    return JsonResponse({"success": True, "purchases": []})

def get_daily_prices(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    prices = DailyPrice.objects.order_by('-date')[:30]
    data = []
    for p in prices:
        data.append({
            "id": p.id,
            "date": p.date.strftime("%Y-%m-%d"),
            "chicken_type": p.chicken_type,
            "price": float(p.price)
        })
    return JsonResponse({
        "success": True,
        "prices": data
    })

def export_invoice_pdf(request, invoice_id):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    try:
        invoice = Invoice.objects.get(invoice_number=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)
        
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Invoice_{invoice.invoice_number}.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"<b>Invoice:</b> {invoice.invoice_number}", styles['Heading1']))
    elements.append(Paragraph(f"<b>Date:</b> {invoice.created_at.strftime('%d %b %Y')}", styles['Normal']))
    elements.append(Paragraph(f"<b>Customer:</b> {invoice.order.customer.customer_name}", styles['Normal']))
    elements.append(Paragraph(f"<b>Order Number:</b> {invoice.order.order_number}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    data = [['Item', 'Weight (kg)', 'Price/kg', 'Subtotal']]
    for item in invoice.items.all():
        sub = float(item.weight_snapshot) * float(item.selling_price_per_kg_snapshot)
        data.append([
            item.chicken_type_snapshot,
            f"{float(item.weight_snapshot):.2f}",
            f"Rs.{float(item.selling_price_per_kg_snapshot):.2f}",
            f"Rs.{sub:.2f}"
        ])
        
    t = Table(data, colWidths=[200, 100, 100, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(t)
    elements.append(Spacer(1, 20))
    
    summary_data = [
        ['GST Type:', invoice.gst_type.capitalize()],
        ['GST Input:', str(invoice.gst_input)],
        ['Calculated GST:', f"Rs.{float(invoice.calculated_gst_amount):.2f}"],
        ['Total Amount:', f"Rs.{float(invoice.total_amount):.2f}"],
        ['Advance Used:', f"Rs.{float(invoice.advance_used):.2f}"],
        ['Total Paid:', f"Rs.{float(invoice.total_payments):.2f}"],
        ['Remaining Balance:', f"Rs.{float(invoice.remaining_amount):.2f}"],
        ['Status:', invoice.status],
    ]
    
    t_sum = Table(summary_data, colWidths=[150, 150])
    t_sum.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))
    elements.append(t_sum)
    
    doc.build(elements)
    return response

def _generate_table_pdf(response, title, headers, data_rows, col_widths=None):
    doc = SimpleDocTemplate(response, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"<b>{title}</b>", styles['Heading1']))
    elements.append(Paragraph(f"Generated: {timezone.now().strftime('%d %b %Y, %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    data = [headers] + data_rows
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 9)
    ]))
    elements.append(t)
    doc.build(elements)
    return response

def export_outstanding_pdf(request):
    invoices = Invoice.objects.select_related('order', 'order__customer').exclude(status='Paid').order_by('-created_at')
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Outstanding_Payments.pdf"'
    
    headers = ['Invoice No', 'Customer', 'Outstanding', 'Due Date', 'Status']
    rows = []
    for i in invoices:
        rem = float(i.remaining_amount)
        if rem > 0:
            rows.append([
                str(i.invoice_number),
                i.order.customer.customer_name,
                f"Rs.{rem:.2f}",
                i.order.delivery_date.strftime("%d %b %Y"),
                i.status
            ])
    return _generate_table_pdf(response, "Outstanding Payments", headers, rows)

def export_advances_pdf(request):
    advances = AdvancePayment.objects.select_related('customer').order_by('-created_at')
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Advances.pdf"'
    
    headers = ['Advance ID', 'Customer', 'Amount', 'Date', 'Note']
    rows = []
    for a in advances:
        rows.append([
            str(a.advance_number),
            a.customer.customer_name,
            f"Rs.{float(a.amount):.2f}",
            a.created_at.strftime("%d %b %Y"),
            a.note or ""
        ])
    return _generate_table_pdf(response, "Customer Advances", headers, rows)

def export_balances_pdf(request):
    customers = Customer.objects.all()
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Advance_Balances.pdf"'
    
    headers = ['Customer', 'Received', 'Consumed', 'Remaining', 'Utilization']
    rows = []
    for c in customers:
        adv_agg = AdvancePayment.objects.filter(customer=c).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        inv_agg = Invoice.objects.filter(order__customer=c).aggregate(Sum('advance_used'))['advance_used__sum'] or Decimal('0.00')
        balance = adv_agg - inv_agg
        if adv_agg > 0:
            percent = (inv_agg / adv_agg) * Decimal('100.00')
            rows.append([
                c.customer_name,
                f"Rs.{float(adv_agg):.2f}",
                f"Rs.{float(inv_agg):.2f}",
                f"Rs.{float(balance):.2f}",
                f"{float(percent):.1f}%"
            ])
    return _generate_table_pdf(response, "Advance Balances", headers, rows)

def export_sales_report_pdf(request):
    invoices = Invoice.objects.select_related('order', 'order__customer').order_by('-created_at')
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Sales_Report.pdf"'
    
    headers = ['Invoice No', 'Customer', 'Date', 'Amount', 'Status']
    rows = []
    for inv in invoices:
        rows.append([
            str(inv.invoice_number),
            inv.order.customer.customer_name,
            inv.created_at.strftime("%d %b %Y"),
            f"Rs.{float(inv.total_amount):.2f}",
            inv.status
        ])
    return _generate_table_pdf(response, "Sales Report", headers, rows)

def export_purchase_orders_pdf(request):
    orders = Order.objects.select_related('customer').filter(status='Ready').order_by('-created_at')
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Purchase_Orders.pdf"'
    
    headers = ['Order No', 'Customer', 'Items', 'Total Weight (Kg)', 'Status']
    rows = []
    for o in orders:
        items_summary = " + ".join([i.chicken_type for i in o.items.all()])
        rows.append([
            str(o.order_number),
            o.customer.customer_name,
            items_summary or "-",
            f"{float(o.total_weight):.2f}",
            o.status
        ])
    return _generate_table_pdf(response, "Pending Purchase Orders", headers, rows)

@csrf_exempt
def save_order_pricing(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        order = Order.objects.get(id=order_id)
        data = json.loads(request.body)
        
        items_data = data.get('items', [])
        
        if not items_data:
            return JsonResponse({"success": False, "message": "Items pricing data is required."}, status=400)
            
        for item_data in items_data:
            item_id = item_data.get('id')
            price_per_kg = item_data.get('price_per_kg')
            
            if item_id and price_per_kg is not None:
                try:
                    order_item = OrderItem.objects.get(id=item_id, order=order)
                    order_item.price_per_kg = float(price_per_kg)
                    order_item.save()
                except OrderItem.DoesNotExist:
                    continue
                    
        return JsonResponse({"success": True, "message": "Pricing saved successfully."})
        
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
