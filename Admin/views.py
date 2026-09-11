from django.shortcuts import render

# Create your views here.
import json

from django.db.models import Q, Sum, Count, F
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, date, timedelta
from django.utils import timezone
from decimal import Decimal
from django.views.decorators.http import require_http_methods
import json

from .models import Customer, Order, OrderItem, DailyPrice, Invoice, InvoiceItem, AdvancePayment, Notification, Category, CustomerCategoryPrice


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

    from django.db.models import Sum, Count
    from decimal import Decimal

    customers = Customer.objects.annotate(
        total_orders=Count('orders', distinct=True),
        total_purchase_volume=Sum('orders__items__weight')
    ).order_by("-created_at")

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
                "performance_score": customer.performance_score,
                "total_orders": customer.total_orders,
                "total_purchase_volume": float(customer.total_purchase_volume or 0),
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
        items = inv.order.items.all()
        if items.exists():
            item_names = [f"{item.chicken_type.capitalize()}" for item in items]
            item_str = ", ".join(item_names)
        elif inv.order.chicken_type:
            item_str = f"{inv.order.chicken_type.capitalize()}"
        else:
            item_str = "Mixed Items"
            
        purchase_history.append({
            "invoice": inv.invoice_number,
            "date": inv.created_at.strftime("%d %b %Y"),
            "item": item_str,
            "weight": f"{float(inv.order.weight)} kg" if inv.order.weight else f"{sum(item.weight for item in items)} kg",
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
                "performance_score": customer.performance_score,
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

@require_http_methods(["GET"])
def get_customer_prices(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
        prices = CustomerCategoryPrice.objects.filter(customer=customer)
        price_dict = {p.category.name: float(p.price) for p in prices}
        return JsonResponse({"success": True, "prices": price_dict})
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)

@csrf_exempt
@require_http_methods(["PUT"])
def update_customer_prices(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
        data = json.loads(request.body)
        prices = data.get('prices', {})
        
        with transaction.atomic():
            for cat_name, price_val in prices.items():
                if price_val == "" or price_val is None:
                    continue
                try:
                    category = Category.objects.get(name=cat_name)
                    # Create or update price
                    CustomerCategoryPrice.objects.update_or_create(
                        customer=customer,
                        category=category,
                        defaults={'price': Decimal(str(price_val))}
                    )
                except Category.DoesNotExist:
                    continue
                    
        return JsonResponse({"success": True, "message": "Prices updated successfully."})
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


@csrf_exempt
def add_order(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON data."}, status=400)

    from .models import OrderItem
    
    customer_id = data.get("customer_id")
    delivery_date = data.get("delivery_date")
    status = data.get("status", "Pending")
    notes = data.get("notes", "")

    # Legacy compatibility vs New multi-item
    items = data.get("items")
    chicken_type = data.get("chicken_type")
    weight = data.get("weight")

    if not customer_id or not delivery_date:
        return JsonResponse({"success": False, "message": "Missing required fields."}, status=400)

    if items is None and not (chicken_type and weight):
        return JsonResponse({"success": False, "message": "Missing items or legacy chicken_type/weight."}, status=400)

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    # Convert legacy format to items array if needed
    if items is None:
        items = [{"chicken_type": chicken_type, "weight": weight}]
    
    if len(items) == 0:
        return JsonResponse({"success": False, "message": "Order must have at least one item."}, status=400)

    # Legacy fields synchronization (using the first item)
    first_item = items[0]

    order = Order.objects.create(
        customer=customer,
        delivery_date=delivery_date,
        chicken_type=first_item.get("chicken_type"),
        weight=first_item.get("weight"),
        status=status,
        notes=notes
    )
    
    # Create OrderItems
    for item in items:
        OrderItem.objects.create(
            order=order,
            chicken_type=item.get("chicken_type"),
            weight=item.get("weight")
        )

    # Create Notification for Cutting Team
    Notification.objects.create(
        type="order",
        title="New Order Received",
        description=f"Order {order.order_number} from {customer.customer_name} has been placed."
    )

    # Build items response
    items_response = [{"id": oi.id, "chicken_type": oi.chicken_type, "weight": str(oi.weight)} for oi in order.items.all()]

    return JsonResponse({
        "success": True,
        "message": "Order added successfully.",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type,
            "weight": str(order.weight) if order.weight else "0",
            "items": items_response,
            "status": order.status,
            "notes": order.notes,
            "created_at": order.created_at,
        }
    }, status=201)

def view_all_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    orders = Order.objects.prefetch_related('items', 'customer').all().order_by("-created_at")
    status = request.GET.get("status", "").strip()
    date = request.GET.get("date", "").strip()

    if status and status.lower() != "all":
        orders = orders.filter(status__iexact=status)

    if date:
        orders = orders.filter(delivery_date=date)

    order_list = []
    for order in orders:
        total_expected_value = Decimal('0.00')
        total_actual_value = Decimal('0.00')
        total_received = Decimal('0.00')
        total_waste = Decimal('0.00')
        total_meat = Decimal('0.00')
        
        items_list = []
        for oi in order.items.all():
            weight = Decimal(str(oi.weight)) if oi.weight else Decimal('0.00')
            price = Decimal(str(oi.price_per_kg)) if oi.price_per_kg else Decimal('0.00')
            received = Decimal(str(oi.received_quantity)) if oi.received_quantity else Decimal('0.00')
            waste = Decimal(str(oi.waste_quantity)) if oi.waste_quantity else Decimal('0.00')
            meat = Decimal(str(oi.meat_delivered)) if oi.meat_delivered else Decimal('0.00')
            
            expected_price = weight * price
            actual_price = meat * price
            
            total_expected_value += expected_price
            total_actual_value += actual_price
            total_received += received
            total_waste += waste
            total_meat += meat
            
            items_list.append({
                "id": oi.id, 
                "chicken_type": oi.chicken_type, 
                "weight": str(oi.weight),
                "price_per_kg": float(oi.price_per_kg) if oi.price_per_kg else None,
                "received_quantity": str(oi.received_quantity) if oi.received_quantity else "",
                "waste_quantity": str(oi.waste_quantity) if oi.waste_quantity else "",
                "meat_delivered": str(oi.meat_delivered) if oi.meat_delivered else "",
                "expected_price": float(expected_price.quantize(Decimal('0.01'))),
                "actual_price": float(actual_price.quantize(Decimal('0.01')))
            })
            
        order_list.append({
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "customer_id": order.customer.id,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type, # legacy
            "weight": str(order.weight) if order.weight else "0", # legacy
            "items": items_list,
            "status": order.status,
            "notes": order.notes,
            "cutting_notes": order.cutting_notes,
            "created_at": order.created_at,
            # Yield Aggregates
            "total_received": float(total_received.quantize(Decimal('0.01'))),
            "total_waste": float(total_waste.quantize(Decimal('0.01'))),
            "total_meat": float(total_meat.quantize(Decimal('0.01'))),
            "total_expected_value": float(total_expected_value.quantize(Decimal('0.01'))),
            "total_actual_value": float(total_actual_value.quantize(Decimal('0.01'))),
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

    from .models import OrderItem

    if "customer_id" in data:
        try:
            order.customer = Customer.objects.get(id=data["customer_id"])
        except Customer.DoesNotExist:
            return JsonResponse({"success": False, "message": "Customer not found."}, status=404)

    if "delivery_date" in data:
        order.delivery_date = data["delivery_date"]
    if "status" in data:
        order.status = data["status"]
    if "notes" in data:
        order.notes = data["notes"]

    # Handle items / legacy dual-write
    items = data.get("items")
    chicken_type = data.get("chicken_type")
    weight = data.get("weight")
    
    if items is not None:
        if len(items) > 0:
            order.chicken_type = items[0].get("chicken_type")
            order.weight = items[0].get("weight")
            # Replace existing items securely
            order.items.all().delete()
            for item in items:
                OrderItem.objects.create(
                    order=order,
                    chicken_type=item.get("chicken_type"),
                    weight=item.get("weight")
                )
    elif chicken_type or weight:
        if chicken_type:
            order.chicken_type = chicken_type
        if weight:
            order.weight = weight
        # Only rewrite if items weren't provided to maintain legacy compatibility
        order.items.all().delete()
        OrderItem.objects.create(
            order=order,
            chicken_type=order.chicken_type,
            weight=order.weight
        )

    order.save()

    items_response = [{"id": oi.id, "chicken_type": oi.chicken_type, "weight": str(oi.weight)} for oi in order.items.all()]

    return JsonResponse({
        "success": True,
        "message": "Order updated successfully.",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "customer_id": order.customer.id,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type, # legacy
            "weight": str(order.weight) if order.weight else "0", # legacy
            "items": items_response,
            "status": order.status,
            "notes": order.notes,
            "created_at": order.created_at,
        }
    })

def get_order_stats(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    from .models import OrderItem

    active_orders = Order.objects.exclude(status__in=['Delivered', 'Cancelled'])
    active_count = active_orders.count()
    
    # Calculate total weight from OrderItem, not legacy Order.weight
    total_weight = OrderItem.objects.filter(order__in=active_orders).aggregate(Sum('weight'))['weight__sum'] or 0
    
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
        active_categories = Category.objects.filter(is_active=True)
        for cat in active_categories:
            c_type = cat.name
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


# --- Category APIs ---
def get_categories(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
    
    categories = Category.objects.filter(is_active=True).order_by('name')
    data = [{"id": c.id, "name": c.name} for c in categories]
    return JsonResponse({"success": True, "categories": data})

@csrf_exempt
def add_category(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)
    
    try:
        data = json.loads(request.body)
        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"success": False, "message": "Category name is required."}, status=400)
            
        category, created = Category.objects.get_or_create(name=name)
        if not created and not category.is_active:
            category.is_active = True
            category.save()
            
        return JsonResponse({"success": True, "message": "Category added.", "category": {"id": category.id, "name": category.name}})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)

@csrf_exempt
def delete_category(request, category_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE method required."}, status=405)
        
    try:
        category = Category.objects.get(id=category_id)
        # Soft delete
        category.is_active = False
        category.save()
        return JsonResponse({"success": True, "message": "Category removed."})
    except Category.DoesNotExist:
        return JsonResponse({"success": False, "message": "Category not found."}, status=404)


# --- Accounts/Invoice APIs ---

def get_accounts_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    orders = Order.objects.filter(status__in=['Ready', 'Delivered']).prefetch_related('items', 'invoice').order_by('-created_at')

    target_date = request.GET.get('date')
    if target_date:
        orders = orders.filter(delivery_date=target_date)

    order_list = []
    for order in orders:
        invoice_data = None
        if hasattr(order, 'invoice'):
            invoice_data = {
                "invoice_number": order.invoice.invoice_number,
                "selling_price_per_kg": float(order.invoice.selling_price_per_kg) if order.invoice.selling_price_per_kg else 0, # legacy fallback
                "gst_amount": float(order.invoice.gst_amount) if order.invoice.gst_amount else 0, # legacy fallback
                "total_amount": float(order.invoice.total_amount),
                "status": order.invoice.status,
            }
        
        total_expected_value = Decimal('0.00')
        total_actual_value = Decimal('0.00')
        total_received = Decimal('0.00')
        total_waste = Decimal('0.00')
        total_meat = Decimal('0.00')
        
        items_list = []
        for oi in order.items.all():
            weight = Decimal(str(oi.weight)) if oi.weight else Decimal('0.00')
            price = Decimal(str(oi.price_per_kg)) if oi.price_per_kg else Decimal('0.00')
            received = Decimal(str(oi.received_quantity)) if oi.received_quantity else Decimal('0.00')
            waste = Decimal(str(oi.waste_quantity)) if oi.waste_quantity else Decimal('0.00')
            meat = Decimal(str(oi.meat_delivered)) if oi.meat_delivered else Decimal('0.00')
            
            expected_price = weight * price
            actual_price = meat * price
            
            total_expected_value += expected_price
            total_actual_value += actual_price
            total_received += received
            total_waste += waste
            total_meat += meat
            
            items_list.append({
                "id": oi.id, 
                "chicken_type": oi.chicken_type, 
                "weight": str(oi.weight),
                "price_per_kg": float(oi.price_per_kg) if oi.price_per_kg else None,
                "received_quantity": str(oi.received_quantity) if oi.received_quantity else "",
                "waste_quantity": str(oi.waste_quantity) if oi.waste_quantity else "",
                "meat_delivered": str(oi.meat_delivered) if oi.meat_delivered else "",
                "expected_price": float(expected_price.quantize(Decimal('0.01'))),
                "actual_price": float(actual_price.quantize(Decimal('0.01')))
            })

        order_list.append({
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "customer_id": order.customer.id,
            "delivery_date": order.delivery_date,
            "chicken_type": order.chicken_type, # legacy
            "weight": str(order.weight) if order.weight else "0", # legacy
            "items": items_list,
            "status": order.status,
            "invoice": invoice_data,
            "cutting_notes": order.cutting_notes,
            # Yield Aggregates
            "total_received": float(total_received.quantize(Decimal('0.01'))),
            "total_waste": float(total_waste.quantize(Decimal('0.01'))),
            "total_meat": float(total_meat.quantize(Decimal('0.01'))),
            "total_expected_value": float(total_expected_value.quantize(Decimal('0.01'))),
            "total_actual_value": float(total_actual_value.quantize(Decimal('0.01'))),
        })

    # Calculate daily category-wise sales
    category_sales = {}
    for order in orders:
        if hasattr(order, 'invoice'): # Only count billed items maybe? The prompt says "Daily category-wise sales". Usually this implies invoiced or at least ready to bill. Let's count all orders in this list (Ready/Delivered).
            pass
        for oi in order.items.all():
            meat = Decimal(str(oi.meat_delivered)) if oi.meat_delivered else Decimal('0.00')
            price = Decimal(str(oi.price_per_kg)) if oi.price_per_kg else Decimal('0.00')
            if meat > 0 and price > 0:
                cat_name = oi.chicken_type
                if cat_name not in category_sales:
                    category_sales[cat_name] = {'weight': Decimal('0.00'), 'value': Decimal('0.00')}
                category_sales[cat_name]['weight'] += meat
                category_sales[cat_name]['value'] += (meat * price)
    
    formatted_sales = {}
    for cat, data in category_sales.items():
        formatted_sales[cat] = {
            'weight': float(data['weight'].quantize(Decimal('0.01'))),
            'value': float(data['value'].quantize(Decimal('0.01')))
        }

    return JsonResponse({"success": True, "orders": order_list, "daily_category_sales": formatted_sales})

@csrf_exempt
def delete_order(request, order_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE method required."}, status=405)
    
    try:
        order = Order.objects.get(id=order_id)
        order.delete()
        return JsonResponse({"success": True, "message": "Order deleted successfully."})
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)

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

@csrf_exempt
def create_invoice(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        order_id = data.get('order_id')
        gst_type = data.get('gst_type', 'fixed')
        gst_input_val = data.get('gst_input', 0)
        
        try:
            gst_input = Decimal(str(gst_input_val))
        except (ValueError, TypeError, Exception):
            gst_input = Decimal('0.00')

        if not order_id:
            return JsonResponse({"success": False, "message": "order_id is required."}, status=400)

        with transaction.atomic():
            # Validate Order
            order = Order.objects.select_for_update().get(id=order_id)
            
            # Lock the customer to prevent concurrent advance consumption
            customer = Customer.objects.select_for_update().get(id=order.customer_id)
            
            # Duplicate protection
            if hasattr(order, 'invoice'):
                return JsonResponse({"success": False, "message": "Invoice already exists for this order."}, status=400)

            items = order.items.all()
            if not items.exists():
                return JsonResponse({"success": False, "message": "Order has no items."}, status=400)

            # Validate prices and calculate subtotal using Decimal
            subtotal = Decimal('0.00')
            for item in items:
                if item.price_per_kg is None or Decimal(str(item.price_per_kg)) < Decimal('0.00'):
                    return JsonResponse({"success": False, "message": f"Missing or invalid price for item: {item.chicken_type}"}, status=400)
                if item.weight is None or Decimal(str(item.weight)) <= Decimal('0.00'):
                    return JsonResponse({"success": False, "message": f"Invalid weight for item: {item.chicken_type}"}, status=400)
                
                item_subtotal = Decimal(str(item.weight)) * Decimal(str(item.price_per_kg))
                subtotal += item_subtotal

            # Quantize subtotal to 2 decimal places
            subtotal = subtotal.quantize(Decimal('0.01'))

            # Calculate GST using Decimal
            if gst_type == 'percentage':
                calculated_gst_amount = subtotal * (gst_input / Decimal('100.00'))
            else:
                calculated_gst_amount = gst_input
                
            calculated_gst_amount = calculated_gst_amount.quantize(Decimal('0.01'))

            total_amount = subtotal + calculated_gst_amount

            # Calculate Customer's available advance balance
            total_advances = AdvancePayment.objects.filter(customer=customer).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
            total_used = Invoice.objects.filter(order__customer=customer).aggregate(Sum('advance_used'))['advance_used__sum'] or Decimal('0.00')
            available_advance = Decimal(str(total_advances)) - Decimal(str(total_used))

            advance_to_use = Decimal('0.00')
            status = 'Unpaid'

            if available_advance > Decimal('0.00'):
                if available_advance >= total_amount:
                    advance_to_use = total_amount
                    status = 'Paid'
                else:
                    advance_to_use = available_advance
                    status = 'Partial'

            # Create Invoice
            invoice = Invoice.objects.create(
                order=order,
                gst_type=gst_type,
                gst_input=gst_input,
                calculated_gst_amount=calculated_gst_amount,
                total_amount=total_amount,
                advance_used=advance_to_use,
                status=status,
                # Legacy fields for compatibility
                selling_price_per_kg=Decimal('0.00'), 
                gst_amount=calculated_gst_amount
            )

            # Create InvoiceItem snapshots
            invoice_items_data = []
            for item in items:
                ii = InvoiceItem.objects.create(
                    invoice=invoice,
                    order_item=item,
                    chicken_type_snapshot=item.chicken_type,
                    weight_snapshot=item.weight,
                    selling_price_per_kg_snapshot=item.price_per_kg
                )
                item_subtotal = Decimal(str(ii.weight_snapshot)) * Decimal(str(ii.selling_price_per_kg_snapshot))
                invoice_items_data.append({
                    "chicken_type": ii.chicken_type_snapshot,
                    "weight": str(ii.weight_snapshot),
                    "selling_price_per_kg": str(ii.selling_price_per_kg_snapshot),
                    "subtotal": float(item_subtotal.quantize(Decimal('0.01')))
                })

            # The Notification model from the existing codebase expects 'type', 'title', 'description'
            Notification.objects.create(
                type="invoice",
                title="Invoice Generated",
                description=f"Invoice {invoice.invoice_number} created for {customer.customer_name}."
            )

            remaining_amount = total_amount - advance_to_use

            response_data = {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "order_id": order.id,
                "items": invoice_items_data,
                "subtotal": float(subtotal),
                "gst_type": gst_type,
                "gst_input": float(gst_input),
                "calculated_gst_amount": float(calculated_gst_amount),
                "total_amount": float(total_amount),
                "advance_used": float(advance_to_use),
                "remaining_amount": float(remaining_amount),
                "status": status
            }

            return JsonResponse({"success": True, "invoice": response_data})

    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found."}, status=404)
    except Customer.DoesNotExist:
        return JsonResponse({"success": False, "message": "Customer not found."}, status=404)
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
        try:
            sd = timezone.make_aware(datetime.strptime(start_date, "%Y-%m-%d"))
            advances = advances.filter(created_at__gte=sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = timezone.make_aware(datetime.strptime(end_date, "%Y-%m-%d")) + timedelta(days=1)
            advances = advances.filter(created_at__lt=ed)
        except ValueError:
            pass
    
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

    period = request.GET.get('period', 'All')
    start_dt, end_dt = get_date_range(period)

    customers = Customer.objects.all()
    balances = []
    
    for customer in customers:
        advances_qs = AdvancePayment.objects.filter(customer=customer)
        invoices_qs = Invoice.objects.filter(order__customer=customer)

        if start_dt and end_dt:
            advances_qs = advances_qs.filter(created_at__gte=start_dt, created_at__lte=end_dt)
            invoices_qs = invoices_qs.filter(created_at__gte=start_dt, created_at__lte=end_dt)

        total_advances = advances_qs.aggregate(Sum('amount'))['amount__sum'] or 0
        total_used = invoices_qs.aggregate(Sum('advance_used'))['advance_used__sum'] or 0
        
        if total_advances > 0 or total_used > 0:
            total_advances = float(total_advances)
            total_used = float(total_used)
            balance = total_advances - total_used
            percent = (total_used / total_advances) * 100 if total_advances > 0 else 0
            
            last_adv = advances_qs.order_by('-created_at').first()
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

    invoices = Invoice.objects.all().prefetch_related('payments').order_by('-created_at')

    period = request.GET.get('period')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if period and period != "All":
        start_dt, end_dt = get_date_range(period)
        if start_dt and end_dt:
            invoices = invoices.filter(created_at__gte=start_dt, created_at__lte=end_dt)
    else:
        if start_date:
            try:
                sd = timezone.make_aware(datetime.strptime(start_date, "%Y-%m-%d"))
                invoices = invoices.filter(created_at__gte=sd)
            except ValueError:
                pass
        if end_date:
            try:
                ed = timezone.make_aware(datetime.strptime(end_date, "%Y-%m-%d")) + timedelta(days=1)
                invoices = invoices.filter(created_at__lt=ed)
            except ValueError:
                pass
    
    data = []
    for inv in invoices:
        balance_due = float(inv.remaining_amount)
        
        data.append({
            "id": inv.invoice_number,
            "customer": inv.order.customer.customer_name,
            "date": inv.created_at.strftime("%d %b %Y"),
            "amount": float(inv.total_amount - inv.calculated_gst_amount),
            "tax": float(inv.calculated_gst_amount),
            "total": float(inv.total_amount),
            "advance_used": float(inv.advance_used),
            "balance": balance_due,
            "status": inv.status
        })

    return JsonResponse({"success": True, "invoices": data})

@csrf_exempt
def add_invoice_payment(request, invoice_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        data = json.loads(request.body)
        amount_val = data.get('amount')
        payment_method = data.get('payment_method', 'Cash')
        reference_no = data.get('reference_no', '')
        note = data.get('note', '')

        try:
            amount = Decimal(str(amount_val))
        except (ValueError, TypeError, Exception):
            return JsonResponse({"success": False, "message": "Invalid amount format."}, status=400)

        if amount <= Decimal('0.00'):
            return JsonResponse({"success": False, "message": "Payment amount must be greater than zero."}, status=400)

        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(id=invoice_id)
            
            if invoice.status == 'Paid' or invoice.remaining_amount <= Decimal('0.00'):
                return JsonResponse({"success": False, "message": "Invoice is already fully paid."}, status=400)

            if amount > invoice.remaining_amount:
                return JsonResponse({"success": False, "message": f"Payment of ₹{amount} exceeds remaining balance of ₹{invoice.remaining_amount}."}, status=400)

            # Create payment
            from .models import InvoicePayment
            InvoicePayment.objects.create(
                invoice=invoice,
                amount=amount,
                payment_method=payment_method,
                reference_no=reference_no,
                note=note
            )

            # Update status
            invoice.update_status()

            return JsonResponse({
                "success": True, 
                "message": "Payment recorded successfully.",
                "remaining_amount": float(invoice.remaining_amount),
                "status": invoice.status
            })

    except Invoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)

def get_invoice_payments(request, invoice_id):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        payments = invoice.payments.all().order_by('created_at')
        
        payment_list = []
        for p in payments:
            payment_list.append({
                "id": p.id,
                "date": p.created_at.strftime("%d %b %Y"),
                "amount": float(p.amount),
                "method": p.payment_method,
                "reference": p.reference_no,
                "note": p.note
            })
            
        return JsonResponse({
            "success": True, 
            "payments": payment_list,
            "total_invoice": float(invoice.total_amount),
            "advance_used": float(invoice.advance_used),
            "total_payments": float(invoice.total_payments),
            "remaining_amount": float(invoice.remaining_amount),
            "status": invoice.status
        })
        
    except Invoice.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invoice not found."}, status=404)


# --- Helper ---
def get_date_range(period):
    now = timezone.now()
    if period == "Daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif period == "Weekly":
        start = now - timedelta(days=7)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif period == "Monthly":
        start = now - timedelta(days=30)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), now
    return None, None

# --- Dashboard & Reports APIs ---

def get_dashboard_stats(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    period = request.GET.get('period', 'All')
    start_dt, end_dt = get_date_range(period)

    # Base QuerySets
    invoices_qs = Invoice.objects.all()
    orders_qs = Order.objects.all()
    customers_qs = Customer.objects.all()

    if start_dt and end_dt:
        invoices_qs = invoices_qs.filter(created_at__gte=start_dt, created_at__lte=end_dt)
        orders_qs = orders_qs.filter(created_at__gte=start_dt, created_at__lte=end_dt)
        customers_qs = customers_qs.filter(created_at__gte=start_dt, created_at__lte=end_dt)

    # Calculate Total Revenue (Sum of all Paid/Partial Invoice total_amount)
    total_revenue = invoices_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Calculate Total Orders
    total_orders = orders_qs.count()
    
    # Calculate Total Customers
    total_customers = customers_qs.count()
    
    # Calculate Outstanding Balance (Sum of Invoice totals minus advance_used minus direct payments)
    unpaid_invoices = invoices_qs.filter(status__in=["Unpaid", "Partial"]).prefetch_related('payments')
    outstanding_balance = 0
    for inv in unpaid_invoices:
        outstanding_balance += float(inv.remaining_amount)
        
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
        
    period = request.GET.get('period', 'Daily')
    if period == 'Daily':
        days = 7
    elif period == 'Weekly':
        days = 30
    elif period == 'Monthly':
        days = 90
    else:
        days = 7
        
    today = date.today()
    chart_data = []
    
    for i in range(days-1, -1, -1):
        d = today - timedelta(days=i)
        
        # Safe timezone-aware range for the day
        start_of_day = timezone.make_aware(datetime.combine(d, datetime.min.time()))
        end_of_day = start_of_day + timedelta(days=1)
        
        # Revenue for this day
        invs = Invoice.objects.filter(created_at__gte=start_of_day, created_at__lt=end_of_day)
        rev = invs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        # Orders for this day
        ords = Order.objects.filter(created_at__gte=start_of_day, created_at__lt=end_of_day).count()
        
        chart_data.append({
            "name": d.strftime("%d %b, %a") if days <= 7 else d.strftime("%d %b"),
            "revenue": float(rev),
            "orders": ords
        })
        
    return JsonResponse({"success": True, "chartData": chart_data})

def get_recent_orders(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    orders = Order.objects.all().prefetch_related('items').order_by('-created_at')[:5]
    data = []
    for order in orders:
        # Calculate total weight from items, fallback to legacy weight if needed
        total_weight = sum([float(item.weight) for item in order.items.all()]) if order.items.exists() else float(order.weight or 0)
        data.append({
            "id": order.order_number,
            "customer": order.customer.customer_name,
            "weight": total_weight,
            "status": order.status,
            "date": order.created_at.strftime("%d %b %Y, %I:%M %p")
        })
        
    return JsonResponse({"success": True, "recent_orders": data})

def get_customer_purchase_report(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)
        
    period = request.GET.get('period', 'All')
    start_dt, end_dt = get_date_range(period)

    customers = Customer.objects.all()
    data = []
    
    from .models import OrderItem
    for c in customers:
        orders = Order.objects.filter(customer=c)
        order_items = OrderItem.objects.filter(order__customer=c)
        invoices = Invoice.objects.filter(order__customer=c)

        if start_dt and end_dt:
            orders = orders.filter(created_at__gte=start_dt, created_at__lte=end_dt)
            order_items = order_items.filter(order__created_at__gte=start_dt, order__created_at__lte=end_dt)
            invoices = invoices.filter(created_at__gte=start_dt, created_at__lte=end_dt)

        total_orders = orders.count()
        
        # Sum weights from OrderItem
        items_weight = order_items.aggregate(Sum('weight'))['weight__sum'] or 0
        total_weight = float(items_weight)
        
        total_spent = invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        data.append({
            "customer": c.customer_name,
            "phone": c.phone,
            "total_orders": total_orders,
            "total_weight": total_weight,
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
