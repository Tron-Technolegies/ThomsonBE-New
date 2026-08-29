from django.shortcuts import render

# Create your views here.
import json

from django.db.models import Q, Sum, Count, F
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, date, timedelta
import json

from .models import Customer, Order, DailyPrice, Invoice, AdvancePayment, Notification


@csrf_exempt
def add_customer(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": "POST method required."
            },
            status=405
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid JSON data."
            },
            status=400
        )

    customer_name = data.get("customer_name")
    company_name = data.get("company_name")
    contact_person = data.get("contact_person")
    phone = data.get("phone")
    email = data.get("email")
    gst_number = data.get("gst_number")
    customer_type = data.get("customer_type")
    status = data.get("status")
    address = data.get("address")

    # Required fields
    if not customer_name:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer name is required."
            },
            status=400
        )

    if not company_name:
        return JsonResponse(
            {
                "success": False,
                "message": "Company name is required."
            },
            status=400
        )

    if not phone:
        return JsonResponse(
            {
                "success": False,
                "message": "Phone is required."
            },
            status=400
        )

    if not address:
        return JsonResponse(
            {
                "success": False,
                "message": "Address is required."
            },
            status=400
        )

    # Default values
    if not customer_type:
        customer_type = "regular"

    if not status:
        status = "active"

    # Validate customer type
    if customer_type not in [
        "regular",
        "wholesale",
        "new_customer"
    ]:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid customer type."
            },
            status=400
        )

    # Validate status
    if status not in [
        "active",
        "inactive"
    ]:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid status."
            },
            status=400
        )

    customer = Customer.objects.create(
        customer_name=customer_name,
        company_name=company_name,
        contact_person=contact_person,
        phone=phone,
        email=email,
        gst_number=gst_number,
        customer_type=customer_type,
        status=status,
        address=address
    )

    return JsonResponse(
        {
            "success": True,
            "message": "Customer added successfully.",
            "customer": {
                "id": customer.id,
                "customer_name": customer.customer_name,
                "company_name": customer.company_name,
                "contact_person": customer.contact_person,
                "phone": customer.phone,
                "email": customer.email,
                "gst_number": customer.gst_number,
                "customer_type": customer.customer_type,
                "status": customer.status,
                "address": customer.address,
                "created_at": customer.created_at,
                "updated_at": customer.updated_at
            }
        },
        status=201
    )


def view_all_customers(request):

    if request.method != "GET":
        return JsonResponse(
            {
                "success": False,
                "message": "GET method required."
            },
            status=405
        )

    customers = Customer.objects.all().order_by("-created_at")

    search = request.GET.get("search", "").strip()
    customer_type = request.GET.get("customer_type", "").strip()
    status = request.GET.get("status", "").strip()

    # Search
    if search:
        customers = customers.filter(
            Q(customer_name__icontains=search)
            | Q(company_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    # Customer type filter
    if customer_type and customer_type != "all":
        customers = customers.filter(
            customer_type=customer_type
        )

    # Status filter
    if status and status != "all":
        customers = customers.filter(
            status=status
        )

    customer_list = []

    for customer in customers:
        customer_list.append(
            {
                "id": customer.id,
                "customer_name": customer.customer_name,
                "company_name": customer.company_name,
                "contact_person": customer.contact_person,
                "phone": customer.phone,
                "email": customer.email,
                "gst_number": customer.gst_number,
                "customer_type": customer.customer_type,
                "status": customer.status,
                "address": customer.address,
                "created_at": customer.created_at,
                "updated_at": customer.updated_at
            }
        )

    return JsonResponse(
        {
            "success": True,
            "count": len(customer_list),
            "customers": customer_list
        }
    )


def view_single_customer(request, customer_id):

    if request.method != "GET":
        return JsonResponse(
            {
                "success": False,
                "message": "GET method required."
            },
            status=405
        )

    try:
        customer = Customer.objects.get(
            id=customer_id
        )

    except Customer.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer not found."
            },
            status=404
        )

    invoices = Invoice.objects.filter(order__customer=customer).order_by('-created_at')
    advances = AdvancePayment.objects.filter(customer=customer).order_by('-created_at')
    
    purchase_history = []
    for inv in invoices:
        purchase_history.append({
            "invoice": inv.invoice_number,
            "date": inv.created_at.strftime("%d %b %Y"),
            "item": f"{inv.order.chicken_type.capitalize()} Chicken",
            "weight": f"{float(inv.order.weight)} kg",
            "amount": f"₹{float(inv.total_amount):,.2f}",
            "status": inv.status
        })
        
    transactions = []
    for inv in invoices:
        transactions.append({
            "date_obj": inv.created_at,
            "date": inv.created_at.strftime("%d %b %Y"),
            "type": "Invoice Raised",
            "reference": inv.invoice_number,
            "mode": "—",
            "amount": f"₹{float(inv.total_amount):,.2f}",
            "amountColor": "text-gray-900"
        })
        if float(inv.advance_used) > 0:
            transactions.append({
                "date_obj": inv.created_at,
                "date": inv.created_at.strftime("%d %b %Y"),
                "type": "Payment Received",
                "reference": inv.invoice_number,
                "mode": "Advance Applied",
                "amount": f"₹{float(inv.advance_used):,.2f}",
                "amountColor": "text-green-500"
            })
            
    for adv in advances:
        transactions.append({
            "date_obj": adv.created_at,
            "date": adv.created_at.strftime("%d %b %Y"),
            "type": "Advance Payment",
            "reference": adv.advance_number,
            "mode": adv.payment_method,
            "amount": f"+₹{float(adv.amount):,.2f}",
            "amountColor": "text-red-500"
        })
        
    transactions.sort(key=lambda x: x['date_obj'], reverse=True)
    for t in transactions:
        t.pop('date_obj', None)
        t['balance'] = "—"

    return JsonResponse(
        {
            "success": True,
            "customer": {
                "id": customer.id,
                "customer_name": customer.customer_name,
                "company_name": customer.company_name,
                "contact_person": customer.contact_person,
                "phone": customer.phone,
                "email": customer.email,
                "gst_number": customer.gst_number,
                "customer_type": customer.customer_type,
                "status": customer.status,
                "address": customer.address,
                "created_at": customer.created_at,
                "updated_at": customer.updated_at,
                "purchase_history": purchase_history,
                "transaction_history": transactions
            }
        }
    )


@csrf_exempt
def edit_customer(request, customer_id):

    if request.method != "PUT":
        return JsonResponse(
            {
                "success": False,
                "message": "PUT method required."
            },
            status=405
        )

    try:
        customer = Customer.objects.get(
            id=customer_id
        )

    except Customer.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer not found."
            },
            status=404
        )

    try:
        data = json.loads(request.body)

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid JSON data."
            },
            status=400
        )

    customer_name = data.get("customer_name")
    company_name = data.get("company_name")
    contact_person = data.get("contact_person")
    phone = data.get("phone")
    email = data.get("email")
    gst_number = data.get("gst_number")
    customer_type = data.get("customer_type")
    status = data.get("status")
    address = data.get("address")

    # Required fields
    if not customer_name:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer name is required."
            },
            status=400
        )

    if not company_name:
        return JsonResponse(
            {
                "success": False,
                "message": "Company name is required."
            },
            status=400
        )

    if not phone:
        return JsonResponse(
            {
                "success": False,
                "message": "Phone is required."
            },
            status=400
        )

    if not address:
        return JsonResponse(
            {
                "success": False,
                "message": "Address is required."
            },
            status=400
        )

    if customer_type not in [
        "regular",
        "wholesale",
        "new_customer"
    ]:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid customer type."
            },
            status=400
        )

    if status not in [
        "active",
        "inactive"
    ]:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid status."
            },
            status=400
        )

    customer.customer_name = customer_name
    customer.company_name = company_name
    customer.contact_person = contact_person
    customer.phone = phone
    customer.email = email
    customer.gst_number = gst_number
    customer.customer_type = customer_type
    customer.status = status
    customer.address = address

    customer.save()

    return JsonResponse(
        {
            "success": True,
            "message": "Customer updated successfully.",
            "customer": {
                "id": customer.id,
                "customer_name": customer.customer_name,
                "company_name": customer.company_name,
                "contact_person": customer.contact_person,
                "phone": customer.phone,
                "email": customer.email,
                "gst_number": customer.gst_number,
                "customer_type": customer.customer_type,
                "status": customer.status,
                "address": customer.address,
                "created_at": customer.created_at,
                "updated_at": customer.updated_at
            }
        }
    )


@csrf_exempt
def delete_customer(request, customer_id):

    if request.method != "DELETE":
        return JsonResponse(
            {
                "success": False,
                "message": "DELETE method required."
            },
            status=405
        )

    try:
        customer = Customer.objects.get(
            id=customer_id
        )

    except Customer.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer not found."
            },
            status=404
        )

    customer.delete()

    return JsonResponse(
        {
            "success": True,
            "message": "Customer deleted successfully."
        }
    )

@csrf_exempt
def add_order(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON data."}, status=400)

    customer_id = data.get("customer_id")
    delivery_date = data.get("delivery_date")
    chicken_type = data.get("chicken_type")
    weight = data.get("weight")
    status = data.get("status", "Pending")
    notes = data.get("notes", "")

    if not customer_id or not delivery_date or not chicken_type or not weight:
        return JsonResponse({"success": False, "message": "Missing required fields."}, status=400)

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    order = Order.objects.create(
        customer=customer,
        delivery_date=delivery_date,
        chicken_type=chicken_type,
        weight=weight,
        status=status,
        notes=notes
    )

    # Create Notification for Cutting Team
    Notification.objects.create(
        type="order",
        title="New Order Received",
        description=f"Order {order.order_number} from {customer.customer_name} has been placed."
    )

    return JsonResponse({
        "success": True,
        "message": "Order added successfully.",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type,
            "weight": order.weight,
            "status": order.status,
            "notes": order.notes,
            "created_at": order.created_at,
        }
    }, status=201)

def view_all_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    orders = Order.objects.all().order_by("-created_at")
    status = request.GET.get("status", "").strip()
    date = request.GET.get("date", "").strip()

    if status and status.lower() != "all":
        orders = orders.filter(status__iexact=status)

    if date:
        orders = orders.filter(delivery_date=date)

    order_list = []
    for order in orders:
        order_list.append({
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "customer_id": order.customer.id,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type,
            "weight": order.weight,
            "status": order.status,
            "notes": order.notes,
            "created_at": order.created_at,
        })

    return JsonResponse({"success": True, "count": len(order_list), "orders": order_list})

@csrf_exempt
def edit_order(request, order_id):
    if request.method != "PUT":
        return JsonResponse({"success": False, "message": "PUT method required."}, status=405)

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found."}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON data."}, status=400)

    if "customer_id" in data:
        try:
            order.customer = Customer.objects.get(id=data["customer_id"])
        except Customer.DoesNotExist:
            return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    if "delivery_date" in data:
        order.delivery_date = data["delivery_date"]
    if "chicken_type" in data:
        order.chicken_type = data["chicken_type"]
    if "weight" in data:
        order.weight = data["weight"]
    if "status" in data:
        order.status = data["status"]
    if "notes" in data:
        order.notes = data["notes"]

    order.save()

    return JsonResponse({
        "success": True,
        "message": "Order updated successfully.",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "customer_id": order.customer.id,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type,
            "weight": order.weight,
            "status": order.status,
            "notes": order.notes,
            "created_at": order.created_at,
        }
    })

def get_order_stats(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    active_orders = Order.objects.exclude(status__in=['Delivered', 'Cancelled'])
    active_count = active_orders.count()
    total_weight = active_orders.aggregate(Sum('weight'))['weight__sum'] or 0
    pending_orders = Order.objects.filter(status__iexact='Pending').count()
    cutting_queue = Order.objects.filter(status__iexact='Cutting').count()
    ready_pickup = Order.objects.filter(status__iexact='Ready').count()

    return JsonResponse({
        "success": True,
        "stats": {
            "active_orders": active_count,
            "total_weight": float(total_weight),
            "pending_orders": pending_orders,
            "cutting_queue": cutting_queue,
            "ready_pickup": ready_pickup
        }
    })

# --- Daily Pricing APIs ---

def get_daily_prices(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    target_date_str = request.GET.get("date")
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = date.today()
    else:
        target_date = date.today()
        
    prices = DailyPrice.objects.filter(date=target_date)
    
    price_map = {p.chicken_type: float(p.price) for p in prices}
    
    return JsonResponse({
        "success": True,
        "date": target_date.strftime('%Y-%m-%d'),
        "prices": price_map
    })

@csrf_exempt
def update_daily_prices(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        prices_data = data.get('prices', {})
        target_date_str = data.get('date')
        
        if target_date_str:
            try:
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = date.today()
        else:
            target_date = date.today()

        updated_prices = {}
        for c_type in dict(Order.CHICKEN_TYPE_CHOICES).keys():
            if c_type in prices_data:
                obj, created = DailyPrice.objects.update_or_create(
                    date=target_date,
                    chicken_type=c_type,
                    defaults={'price': prices_data[c_type]}
                )
                updated_prices[c_type] = float(obj.price)

        return JsonResponse({
            "success": True,
            "message": "Daily prices updated successfully.",
            "prices": updated_prices,
            "date": target_date.strftime('%Y-%m-%d')
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


# --- Accounts/Invoice APIs ---

def get_accounts_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    orders = Order.objects.filter(status__in=['Ready', 'Delivered']).order_by('-created_at')

    target_date = request.GET.get('date')
    if target_date:
        orders = orders.filter(delivery_date=target_date)

    order_list = []
    for order in orders:
        invoice_data = None
        if hasattr(order, 'invoice'):
            invoice_data = {
                "invoice_number": order.invoice.invoice_number,
                "selling_price_per_kg": float(order.invoice.selling_price_per_kg),
                "gst_amount": float(order.invoice.gst_amount),
                "total_amount": float(order.invoice.total_amount),
                "status": order.invoice.status,
            }
        
        order_list.append({
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type,
            "weight": float(order.weight),
            "status": order.status,
            "invoice": invoice_data
        })

    return JsonResponse({"success": True, "orders": order_list})

@csrf_exempt
def create_invoice(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        order_id = data.get('order_id')
        selling_price_per_kg = float(data.get('selling_price_per_kg', 0))
        gst_amount = float(data.get('gst_amount', 0))
        total_amount = float(data.get('total_amount', 0))

        order = Order.objects.get(id=order_id)
        customer = order.customer

        # Calculate Customer's available advance balance
        total_advances = AdvancePayment.objects.filter(customer=customer).aggregate(Sum('amount'))['amount__sum'] or 0
        total_used = Invoice.objects.filter(order__customer=customer).aggregate(Sum('advance_used'))['advance_used__sum'] or 0
        available_advance = float(total_advances) - float(total_used)

        advance_to_use = 0
        status = 'Unpaid'

        if available_advance > 0:
            if available_advance >= total_amount:
                advance_to_use = total_amount
                status = 'Paid'
            else:
                advance_to_use = available_advance
                status = 'Partial'

        invoice, created = Invoice.objects.update_or_create(
            order=order,
            defaults={
                'selling_price_per_kg': selling_price_per_kg,
                'gst_amount': gst_amount,
                'total_amount': total_amount,
                'advance_used': advance_to_use,
                'status': status
            }
        )

        if created:
            Notification.objects.create(
                type="invoice",
                title="Invoice Generated",
                description=f"Invoice {invoice.invoice_number} created for {customer.customer_name}."
            )

        return JsonResponse({
            "success": True,
            "message": "Invoice saved successfully.",
            "invoice_number": invoice.invoice_number,
            "status": invoice.status
        })
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


# --- Advance APIs ---

def get_advances(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    advances = AdvancePayment.objects.all().order_by('-created_at')

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        advances = advances.filter(created_at__date__gte=start_date)
    if end_date:
        advances = advances.filter(created_at__date__lte=end_date)
    
    data = []
    for adv in advances:
        data.append({
            "id": adv.advance_number,
            "customer": adv.customer.customer_name,
            "amount": float(adv.amount),
            "payment_method": adv.payment_method,
            "reference_no": adv.reference_no,
            "date": adv.created_at.strftime("%d %b %Y"),
            "note": adv.note
        })
        
    return JsonResponse({"success": True, "advances": data})

@csrf_exempt
def record_advance(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        customer_id = data.get('customer_id')
        amount = data.get('amount')
        payment_method = data.get('payment_method')
        reference_no = data.get('reference_no', '')
        note = data.get('note', '')

        customer = Customer.objects.get(id=customer_id)
        
        adv = AdvancePayment.objects.create(
            customer=customer,
            amount=amount,
            payment_method=payment_method,
            reference_no=reference_no,
            note=note
        )

        Notification.objects.create(
            type="payment",
            title="Advance Received",
            description=f"Received ₹{amount} from {customer.customer_name}."
        )

        return JsonResponse({"success": True, "message": "Advance recorded", "advance_number": adv.advance_number})
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)

def get_advance_balances(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    customers = Customer.objects.all()
    balances = []
    
    for customer in customers:
        total_advances = AdvancePayment.objects.filter(customer=customer).aggregate(Sum('amount'))['amount__sum'] or 0
        total_used = Invoice.objects.filter(order__customer=customer).aggregate(Sum('advance_used'))['advance_used__sum'] or 0
        
        if total_advances > 0:
            total_advances = float(total_advances)
            total_used = float(total_used)
            balance = total_advances - total_used
            percent = (total_used / total_advances) * 100 if total_advances > 0 else 0
            
            last_adv = AdvancePayment.objects.filter(customer=customer).order_by('-created_at').first()
            last_tx = last_adv.created_at.strftime("%d %b %Y") if last_adv else "-"
            
            balances.append({
                "customer_name": customer.customer_name,
                "received": total_advances,
                "consumed": total_used,
                "balance": balance,
                "percent": int(percent),
                "last_tx": last_tx
            })

    return JsonResponse({"success": True, "balances": balances})

def get_all_invoices(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    invoices = Invoice.objects.all().order_by('-created_at')

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        invoices = invoices.filter(created_at__date__gte=start_date)
    if end_date:
        invoices = invoices.filter(created_at__date__lte=end_date)
    
    data = []
    for inv in invoices:
        balance_due = float(inv.total_amount) - float(inv.advance_used)
        
        data.append({
            "id": inv.invoice_number,
            "customer": inv.order.customer.customer_name,
            "date": inv.created_at.strftime("%d %b %Y"),
            "amount": float(inv.order.weight * inv.selling_price_per_kg),
            "tax": float(inv.gst_amount),
            "total": float(inv.total_amount),
            "advance_used": float(inv.advance_used),
            "balance": balance_due,
            "status": inv.status
        })

    return JsonResponse({"success": True, "invoices": data})


# --- Dashboard & Reports APIs ---

def get_dashboard_stats(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    # Calculate Total Revenue (Sum of all Paid/Partial Invoice total_amount)
    total_revenue = Invoice.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Calculate Total Orders
    total_orders = Order.objects.count()
    
    # Calculate Total Customers
    total_customers = Customer.objects.count()
    
    # Calculate Outstanding Balance (Sum of Invoice totals minus advance_used)
    invoices = Invoice.objects.filter(status__in=["Unpaid", "Partial"])
    outstanding_balance = 0
    for inv in invoices:
        outstanding_balance += float(inv.total_amount) - float(inv.advance_used)
        
    return JsonResponse({
        "success": True,
        "revenue": float(total_revenue),
        "orders": total_orders,
        "customers": total_customers,
        "outstanding": float(outstanding_balance)
    })

def get_dashboard_charts(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    # Get last 7 days of sales for chart
    today = date.today()
    chart_data = []
    
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        
        # Revenue for this day
        invs = Invoice.objects.filter(created_at__date=d)
        rev = invs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        # Orders for this day
        ords = Order.objects.filter(order_date=d).count()
        
        chart_data.append({
            "name": d.strftime("%d %b, %a"),
            "revenue": float(rev),
            "orders": ords
        })
        
    return JsonResponse({"success": True, "chartData": chart_data})

def get_recent_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    orders = Order.objects.all().order_by('-created_at')[:5]
    data = []
    for order in orders:
        data.append({
            "id": order.order_number,
            "customer": order.customer.customer_name,
            "weight": float(order.weight),
            "status": order.status,
            "date": order.created_at.strftime("%d %b %Y, %I:%M %p")
        })
        
    return JsonResponse({"success": True, "recent_orders": data})

def get_sales_report(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    invoices = Invoice.objects.all().order_by('-created_at')
    data = []
    
    for inv in invoices:
        data.append({
            "invoice_no": inv.invoice_number,
            "date": inv.created_at.strftime("%d %b %Y"),
            "customer": inv.order.customer.customer_name,
            "amount": float(inv.total_amount),
            "status": inv.status
        })
        
    return JsonResponse({"success": True, "sales": data})

def get_customer_purchase_report(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    customers = Customer.objects.all()
    data = []
    
    for c in customers:
        orders = Order.objects.filter(customer=c)
        total_orders = orders.count()
        total_weight = orders.aggregate(Sum('weight'))['weight__sum'] or 0
        
        invoices = Invoice.objects.filter(order__customer=c)
        total_spent = invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        data.append({
            "customer": c.customer_name,
            "phone": c.phone_number,
            "total_orders": total_orders,
            "total_weight": float(total_weight),
            "total_spent": float(total_spent)
        })
        
    return JsonResponse({"success": True, "customers_report": data})


# --- Notifications APIs ---

def get_notifications(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    notifs = Notification.objects.all().order_by('-created_at')
    data = []
    for n in notifs:
        data.append({
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "description": n.description,
            "is_read": n.is_read,
            "time": n.created_at.strftime("%I:%M %p, %d %b")
        })
        
    return JsonResponse({"success": True, "notifications": data})

@csrf_exempt
def mark_notifications_read(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)
        
    Notification.objects.filter(is_read=False).update(is_read=True)
    return JsonResponse({"success": True, "message": "All notifications marked as read."})

@csrf_exempt
def clear_notifications(request):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE method required."}, status=405)
        
    Notification.objects.all().delete()
    return JsonResponse({"success": True, "message": "All notifications cleared."})

def get_all_invoices(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    invoices = Invoice.objects.all().order_by('-created_at')
    data = []
    for i in invoices:
        data.append({
            "id": i.invoice_number,
            "customer": i.order.customer.customer_name,
            "date": i.created_at.strftime("%d %b %Y"),
            "amount": float(i.total_amount - i.gst_amount),
            "tax": float(i.gst_amount),
            "total": float(i.total_amount),
            "status": i.status
        })
        
    return JsonResponse({"success": True, "invoices": data})