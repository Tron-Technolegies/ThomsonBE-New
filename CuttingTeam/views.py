from decimal import Decimal, InvalidOperation
import json
from datetime import date
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from Admin.models import Order, Notification

def serialize_cutting_order(order):
    """
    Serialize only the operational fields needed for the Cutting Team.
    Financial fields MUST NOT be included.
    """

    items_list = []

    if hasattr(order, 'items'):

        for item in order.items.all():

            received = (
                Decimal(str(item.received_quantity))
                if item.received_quantity is not None
                else Decimal('0.00')
            )

            meat = (
                Decimal(str(item.meat_delivered))
                if item.meat_delivered is not None
                else Decimal('0.00')
            )

            approx_yield = (
                Decimal(str(item.approx_yield_percentage))
                if item.approx_yield_percentage is not None
                else Decimal('0.00')
            )

            # Expected meat based on approximate yield
            expected_meat = (
                received * approx_yield / Decimal('100')
            )

            # Actual yield based on actual meat
            actual_yield = Decimal('0.00')

            if received > 0:
                actual_yield = (
                    meat / received
                ) * Decimal('100')

            items_list.append({
                "id": item.id,
                "chicken_type": item.chicken_type,
                "weight": str(item.weight),

                # Cutting input/output
                "received_quantity": (
                    str(item.received_quantity)
                    if item.received_quantity is not None
                    else ""
                ),

                "meat_delivered": (
                    str(item.meat_delivered)
                    if item.meat_delivered is not None
                    else ""
                ),

                "waste_quantity": (
                    str(item.waste_quantity)
                    if item.waste_quantity is not None
                    else ""
                ),

                # Yield information
                "approx_yield_percentage": float(
                    approx_yield.quantize(Decimal('0.01'))
                ),

                "expected_meat": float(
                    expected_meat.quantize(Decimal('0.01'))
                ),

                "actual_yield_percentage": float(
                    actual_yield.quantize(Decimal('0.01'))
                ),
            })

    return {
        "id": order.order_number,
        "customer": order.customer.customer_name,
        "type": order.chicken_type,
        "weight": str(order.weight) if order.weight else "0",
        "items": items_list,
        "status": order.status,
        "delivery_date": (
            order.delivery_date.isoformat()
            if order.delivery_date
            else None
        ),
        "cutting_notes": order.cutting_notes or "",
        "notes": order.notes
    }

@require_http_methods(["GET"])
def get_cutting_dashboard(request):
    today = date.today()
    orders_today = Order.objects.filter(delivery_date=today)
    
    today_orders_count = orders_today.count()
    pending_count = orders_today.filter(status="Pending").count()
    cutting_count = orders_today.filter(status="Cutting").count()
    ready_count = orders_today.filter(status="Ready").count()
    
    recent_orders = orders_today.prefetch_related('items', 'customer').order_by('-created_at')[:10]
    serialized_recent = [serialize_cutting_order(o) for o in recent_orders]
    
    return JsonResponse({
        "status": "success",
        "data": {
            "today_orders_count": today_orders_count,
            "pending_count": pending_count,
            "cutting_count": cutting_count,
            "ready_count": ready_count,
            "recent_orders": serialized_recent
        }
    })

@require_http_methods(["GET"])
def get_cutting_orders(request):
    # Could optionally filter by date here
    date_param = request.GET.get('date')
    if date_param:
        orders = Order.objects.filter(delivery_date=date_param).prefetch_related('items', 'customer').order_by('-created_at')
    else:
        # Return all orders ordered by delivery date and created_at
        orders = Order.objects.all().prefetch_related('items', 'customer').order_by('-delivery_date', '-created_at')
    
    serialized_orders = [serialize_cutting_order(o) for o in orders]
    return JsonResponse({
        "status": "success",
        "data": serialized_orders
    })

@csrf_exempt
@require_http_methods(["PUT"])
def update_cutting_order(request, order_number):
    try:
        order = Order.objects.get(order_number=order_number)
    except Order.DoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "Order not found"},
            status=404
        )

    try:
        data = json.loads(request.body)

        new_status = data.get("status")
        notes = data.get("cutting_notes")
        items_data = data.get("items", [])

        if not new_status:
            return JsonResponse(
                {"status": "error", "message": "Status is required"},
                status=400
            )

        # Cutting team can only transition orders to these states
        allowed_statuses = ["Pending", "Cutting", "Ready"]

        if new_status not in allowed_statuses:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Invalid status transition for Cutting team"
                },
                status=400
            )

        # -----------------------------------
        # Update Order
        # -----------------------------------

        update_fields = ["status", "updated_at"]
        order.status = new_status

        if notes is not None:
            order.cutting_notes = notes
            update_fields.append("cutting_notes")

        order.save(update_fields=update_fields)

        # -----------------------------------
        # Update Order Items
        # -----------------------------------

        if items_data:
            from Admin.models import OrderItem

            for item_data in items_data:

                item_id = item_data.get("id")

                if not item_id:
                    continue

                try:
                    item = OrderItem.objects.get(
                        id=item_id,
                        order=order
                    )

                    received_value = item_data.get(
                        "received_quantity"
                    )

                    meat_value = item_data.get(
                        "meat_delivered"
                    )

                    # -----------------------------------
                    # Empty received quantity
                    # -----------------------------------

                    if received_value in [None, ""]:

                        item.received_quantity = None
                        item.meat_delivered = None
                        item.waste_quantity = None

                    else:

                        try:
                            received = Decimal(
                                str(received_value)
                            )

                            if received < 0:
                                return JsonResponse(
                                    {
                                        "status": "error",
                                        "message": (
                                            "Received quantity "
                                            "cannot be negative."
                                        )
                                    },
                                    status=400
                                )

                            # Save raw/live quantity
                            item.received_quantity = received

                            # -----------------------------------
                            # Actual Meat
                            # -----------------------------------

                            if meat_value not in [None, ""]:

                                meat = Decimal(
                                    str(meat_value)
                                )

                                if meat < 0:
                                    return JsonResponse(
                                        {
                                            "status": "error",
                                            "message": (
                                                "Meat quantity "
                                                "cannot be negative."
                                            )
                                        },
                                        status=400
                                    )

                                if meat > received:
                                    return JsonResponse(
                                        {
                                            "status": "error",
                                            "message": (
                                                "Meat quantity cannot "
                                                "be greater than "
                                                "received quantity."
                                            )
                                        },
                                        status=400
                                    )

                                item.meat_delivered = meat

                                # -----------------------------------
                                # Actual Waste
                                # -----------------------------------

                                item.waste_quantity = (
                                    received - meat
                                )

                            else:

                                item.meat_delivered = None
                                item.waste_quantity = None

                        except (
                            InvalidOperation,
                            ValueError,
                            TypeError
                        ):
                            return JsonResponse(
                                {
                                    "status": "error",
                                    "message": (
                                        "Invalid quantity value."
                                    )
                                },
                                status=400
                            )

                    item.save(
                        update_fields=[
                            "received_quantity",
                            "waste_quantity",
                            "meat_delivered"
                        ]
                    )

                except OrderItem.DoesNotExist:
                    continue

        # -----------------------------------
        # Notify Admin
        # -----------------------------------

        Notification.objects.create(
            type="order",
            title="Order Updated by Cutting Team",
            description=(
                f"Order {order.order_number} for "
                f"{order.customer.customer_name} "
                f"is now {new_status}."
            )
        )

        # -----------------------------------
        # Return Updated Order
        # -----------------------------------

        return JsonResponse(
            {
                "status": "success",
                "message": "Order updated successfully",
                "data": serialize_cutting_order(order)
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "status": "error",
                "message": "Invalid JSON"
            },
            status=400
        )

    except Exception as e:
        return JsonResponse(
            {
                "status": "error",
                "message": str(e)
            },
            status=500
        )


@require_http_methods(["GET"])
def get_cutting_notifications(request):
    # Only get order and alert notifications to respect financial data isolation
    notifications = Notification.objects.filter(type__in=["order", "alert"]).order_by('-created_at')[:50]
    
    serialized = []
    for notif in notifications:
        # map backend type to frontend icon type
        ui_type = "info"
        if notif.type == "alert":
            ui_type = "alert"
        elif "delay" in notif.title.lower():
            ui_type = "warning"
        elif "ready" in notif.title.lower() or "completed" in notif.title.lower():
            ui_type = "success"
            
        now = timezone.now()
        diff = now - notif.created_at
        seconds = diff.total_seconds()
        if seconds < 60:
            time_str = "just now"
        elif seconds < 3600:
            time_str = f"{int(seconds // 60)} minutes ago"
        elif seconds < 86400:
            time_str = f"{int(seconds // 3600)} hours ago"
        else:
            time_str = f"{int(seconds // 86400)} days ago"

        serialized.append({
            "id": notif.id,
            "title": notif.title,
            "message": notif.description,
            "type": ui_type,
            "isRead": notif.is_read,
            "time": time_str
        })
        
    return JsonResponse({
        "status": "success",
        "data": serialized
    })

@csrf_exempt
@require_http_methods(["PUT"])
def mark_cutting_notifications_read(request):
    # Mark relevant notifications as read
    Notification.objects.filter(type__in=["order", "alert"], is_read=False).update(is_read=True)
    return JsonResponse({"status": "success", "message": "Notifications marked as read"})

@csrf_exempt
@require_http_methods(["DELETE"])
def clear_cutting_notifications(request):
    # Delete relevant notifications
    Notification.objects.filter(type__in=["order", "alert"]).delete()
    return JsonResponse({"status": "success", "message": "Notifications cleared"})
