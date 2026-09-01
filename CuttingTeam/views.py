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
        items_list = [{"id": item.id, "chicken_type": item.chicken_type, "weight": str(item.weight)} for item in order.items.all()]
        
    return {
        "id": order.order_number,
        "customer": order.customer.customer_name,
        "type": order.chicken_type, # legacy
        "weight": str(order.weight) if order.weight else "0", # legacy
        "items": items_list,
        "status": order.status,
        "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
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
def update_cutting_order_status(request, order_number):
    try:
        order = Order.objects.get(order_number=order_number)
    except Order.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Order not found"}, status=404)
        
    try:
        data = json.loads(request.body)
        new_status = data.get("status")
        
        if not new_status:
            return JsonResponse({"status": "error", "message": "Status is required"}, status=400)
            
        # Cutting team can only transition orders to these operational states
        allowed_statuses = ["Pending", "Cutting", "Ready"]
        if new_status not in allowed_statuses:
            return JsonResponse({"status": "error", "message": "Invalid status transition for Cutting team"}, status=400)
            
        # We only update the status field to ensure no other fields (e.g. weight, financial fields) are modified
        order.status = new_status
        order.save(update_fields=['status', 'updated_at'])
        
        # Notify admin of the status change
        Notification.objects.create(
            type="order",
            title="Order Status Updated",
            description=f"Order {order.order_number} for {order.customer.customer_name} is now {new_status}."
        )
        
        return JsonResponse({
            "status": "success",
            "message": "Order status updated successfully",
            "data": serialize_cutting_order(order)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


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
