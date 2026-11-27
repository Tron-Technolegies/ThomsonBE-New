from unittest import result

from Admin.models import Invoice, Order, OrderItem, InvoiceItem, AdvancePayment, InvoicePayment, Customer, DailyPrice,Category,CustomerCategoryPrice
from django.http import JsonResponse, HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Sum, Count, F
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt

from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch
from django.views.decorators.http import require_GET
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated


class CanManageCustomerPayments(BasePermission):
    message = "Only Admin and Accounts staff can manage payments."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if not user.is_active:
            return False

        if user.is_superuser:
            return True

        profile = getattr(user, "staff_profile", None)

        return bool(
            profile and profile.role in ("admin", "accounts")
        )



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
            "invoice_id": i.id,
            "order_id": i.order.order_number,
            "customer": i.order.customer.customer_name,
            "customer_address": i.order.customer.address or "",
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
        return JsonResponse({
            "success": False,
            "message": "GET method required."
        }, status=405)


    orders = (
        Order.objects
        .filter(status__in=["Ready", "Delivered"])
        .prefetch_related("items")
        .select_related("customer", "invoice")
        .order_by("-created_at")
    )

    target_date = request.GET.get("date")

    if target_date:
        orders = orders.filter(delivery_date=target_date)

    order_list = []

    for order in orders:
        items_list = []
        total_weight = Decimal("0.00")

        for oi in order.items.all():

            weight = (
                Decimal(str(oi.weight))
                if oi.weight is not None
                else Decimal("0.00")
            )

            total_weight += weight
            yield_percentage = oi.approx_yield_percentage

        # Fetch current category yield if the order item has no valid yield
            if (
                yield_percentage is None
                or Decimal(str(yield_percentage)) <= 0
            ):
                yield_percentage = Category.objects.filter(
                    name__iexact=oi.chicken_type
                ).values_list(
                    "approx_yield_percentage",
                    flat=True
                ).first()

            items_list.append({
                "id": oi.id,
                "chicken_type": oi.chicken_type,
                "weight": str(oi.weight),

                "price_per_kg": (
                    float(oi.price_per_kg)
                    if oi.price_per_kg is not None
                    else None
                ),

                # Yield percentage required by invoice frontend
                "approx_yield_percentage": (
                    float(yield_percentage)
                    if yield_percentage is not None
                    else None
                )
            })

        order_list.append({
            "id": order.id,
            "order_number": order.order_number,
            "customer": order.customer.customer_name,
            "customer_id": order.customer_id,  # ADD THIS
            "delivery_date": order.delivery_date.strftime("%d %b %Y"),
            "status": order.status,
            "items": items_list,
            "total_weight": float(total_weight),
            "is_priced": hasattr(order, "invoice"),
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
        return JsonResponse({
            "success": False,
            "message": "POST method required."
        }, status=405)

    try:
        data = json.loads(request.body or "{}")

        order_id = data.get("order_id")
        pricing_mode = data.get("pricing_mode", "live_rate")
        gst_type = data.get("gst_type", "percentage")
        gst_input_raw = data.get("gst_input", 0)

        # Validate pricing mode
        if pricing_mode not in ["live_rate", "meat_rate"]:
            return JsonResponse({
                "success": False,
                "message": "Invalid pricing mode."
            }, status=400)

        if not order_id:
            return JsonResponse({
                "success": False,
                "message": "Order ID is required."
            }, status=400)

        # Validate GST
        try:
            gst_input = Decimal(str(gst_input_raw)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            if not gst_input.is_finite() or gst_input < 0:
                raise InvalidOperation

        except (InvalidOperation, TypeError, ValueError):
            return JsonResponse({
                "success": False,
                "message": "Invalid GST value."
            }, status=400)

        if gst_type not in ["percentage", "fixed"]:
            return JsonResponse({
                "success": False,
                "message": "Invalid GST type."
            }, status=400)

        # Pricing date
        pricing_date = timezone.localdate()

        # Get and lock order
        try:
            order = Order.objects.select_for_update().get(id=order_id)
        except Order.DoesNotExist:
            return JsonResponse({
                "success": False,
                "message": "Order not found."
            }, status=404)

        if order.status not in ["Ready", "Delivered"]:
            return JsonResponse({
                "success": False,
                "message": f"Cannot generate invoice for order in {order.status} status."
            }, status=400)

        # Prevent duplicate invoices
        if hasattr(order, "invoice"):
            return JsonResponse({
                "success": False,
                "message": "Invoice already exists for this order."
            }, status=400)

        items = list(order.items.all())
        # Read invoice-level rate overrides from the frontend.
        item_rates_payload = data.get("item_rates", [])

        if not isinstance(item_rates_payload, list):
            return JsonResponse({
                "success": False,
                "message": "Invalid item rates data."
            }, status=400)

        submitted_rates = {}
        submitted_meat_rates = {}

        for rate_data in item_rates_payload:
            if not isinstance(rate_data, dict):
                return JsonResponse({
                    "success": False,
                    "message": "Invalid item rate entry."
                }, status=400)

            item_id = str(rate_data.get("order_item_id", ""))

            if not item_id or item_id in submitted_rates:
                return JsonResponse({
                    "success": False,
                    "message": "Invalid or duplicate order item rate."
                }, status=400)

            submitted_rates[item_id] = rate_data.get("live_rate")

            manual_meat_rate = rate_data.get("meat_rate")

            if manual_meat_rate is not None:
                try:
                    manual_meat_rate = Decimal(
                        str(manual_meat_rate)
                    ).quantize(
                        Decimal("0.01"),
                        rounding=ROUND_HALF_UP
                    )

                    if (
                        not manual_meat_rate.is_finite()
                        or manual_meat_rate <= 0
                    ):
                        raise ValueError()

                except (ValueError, TypeError, InvalidOperation):
                    return JsonResponse({
                        "success": False,
                        "message": "Invalid manual Meat Rate."
                    }, status=400)

                submitted_meat_rates[item_id] = manual_meat_rate


        valid_item_ids = {str(item.id) for item in items}

        if set(submitted_rates) - valid_item_ids:
            return JsonResponse({
                "success": False,
                "message": "An invalid order item was submitted."
            }, status=400)

        # Fetch customer-specific rates.
        customer_price_map = {
            str(price.category.name).strip().casefold(): price.price
            for price in CustomerCategoryPrice.objects.filter(
                customer=order.customer
            ).select_related("category")
        }

        if not items:
            return JsonResponse({
                "success": False,
                "message": "Order has no items."
            }, status=400)

        # Fetch Daily Prices for the exact pricing date
        daily_prices = DailyPrice.objects.filter(
            date=pricing_date
        ).order_by("-updated_at")

        price_map = {}

        for daily_price in daily_prices:
            key = str(daily_price.chicken_type).strip().casefold()

            if key and key not in price_map:
                price_map[key] = daily_price.price

        # Calculate each order item
        subtotal = Decimal("0.00")
        calculated_items = []

        for item in items:

            chicken_type = str(item.chicken_type).strip()
            key = chicken_type.casefold()

            # Get Daily Live Rate
            if str(item.id) in submitted_rates:
                live_rate_raw = submitted_rates[str(item.id)]

            elif key in customer_price_map:
                live_rate_raw = customer_price_map[key]

            else:
                live_rate_raw = price_map.get(key)

            if live_rate_raw is None:
                return JsonResponse({
                    "success": False,
                    "message": (
                        f"No customer-specific or daily Live Rate "
                        f"found for {chicken_type}."
                    )
                }, status=400)

            live_rate = Decimal(str(live_rate_raw)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            if not live_rate.is_finite() or live_rate <= 0:
                return JsonResponse({
                    "success": False,
                    "message": f"Invalid Daily Live Rate for {chicken_type}."
                }, status=400)

            # Get and validate weight
            weight = Decimal(str(item.weight)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            if not weight.is_finite() or weight <= 0:
                return JsonResponse({
                    "success": False,
                    "message": f"Invalid weight for {chicken_type}."
                }, status=400)

            # Get Yield Percentage
            yield_percentage_raw = item.approx_yield_percentage

            if (
                yield_percentage_raw is None
                or Decimal(str(yield_percentage_raw)) <= 0
            ):
                yield_percentage_raw = Category.objects.filter(
                    name__iexact=chicken_type
                ).values_list(
                    "approx_yield_percentage",
                    flat=True
                ).first()

            yield_percentage = None

            if yield_percentage_raw is not None:
                yield_percentage = Decimal(str(yield_percentage_raw))

                if (
                    not yield_percentage.is_finite()
                    or yield_percentage <= 0
                    or yield_percentage > 100
                ):
                    yield_percentage = None

            # LIVE RATE MODE
            if pricing_mode == "live_rate":

                selected_rate = live_rate
                meat_rate = None

            # MEAT RATE MODE

            # MEAT RATE MODE
            else:
                manual_meat_rate = submitted_meat_rates.get(
                    str(item.id)
                )

                if manual_meat_rate is not None:
                    # Use manually entered Meat Rate
                    meat_rate = manual_meat_rate

                else:
                    # Keep existing automatic calculation
                    if yield_percentage is None:
                        return JsonResponse({
                            "success": False,
                            "message": (
                                f"Valid Yield Percentage is required "
                                f"for {chicken_type}."
                            )
                        }, status=400)

                    meat_rate = (
                        live_rate * Decimal("100") / yield_percentage
                    ).quantize(
                        Decimal("0.01"),
                        rounding=ROUND_HALF_UP
                    )

                selected_rate = meat_rate


            # Calculate item subtotal
            item_subtotal = (
                weight * selected_rate
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            subtotal += item_subtotal

            calculated_items.append({
                "order_item": item,
                "chicken_type": chicken_type,
                "weight": weight,
                "live_rate": live_rate,
                "yield_percentage": yield_percentage,
                "meat_rate": meat_rate,
                "selected_rate": selected_rate,
                "subtotal": item_subtotal,
            })

        subtotal = subtotal.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # Calculate GST
        if gst_type == "percentage":
            calculated_gst_amount = (
                subtotal * gst_input / Decimal("100")
            )
        else:
            calculated_gst_amount = gst_input

        calculated_gst_amount = calculated_gst_amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        total_amount = (
            subtotal + calculated_gst_amount
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # Calculate available customer advance
        customer = order.customer

        total_advances = (
            AdvancePayment.objects
            .filter(customer=customer)
            .aggregate(Sum("amount"))["amount__sum"]
            or Decimal("0.00")
        )

        total_used = (
            Invoice.objects
            .filter(order__customer=customer)
            .aggregate(Sum("advance_used"))["advance_used__sum"]
            or Decimal("0.00")
        )

        available_advance = total_advances - total_used

        advance_used = Decimal("0.00")

        if available_advance > 0:
            advance_used = min(
                available_advance,
                total_amount
            )

        # Determine invoice status
        remaining_amount = total_amount - advance_used

        if remaining_amount <= 0:
            status = "Paid"
        elif advance_used > 0:
            status = "Partial"
        else:
            status = "Unpaid"

        # Create Invoice
        invoice = Invoice.objects.create(
            order=order,
            pricing_mode=pricing_mode,
            pricing_date=pricing_date,
            entered_rate=None,
            gst_type=gst_type,
            gst_input=gst_input,
            gst_amount=calculated_gst_amount,
            calculated_gst_amount=calculated_gst_amount,
            total_amount=total_amount,
            advance_used=advance_used,
            status=status
        )

        # Save invoice items and snapshots
        invoice_items = []

        for row in calculated_items:

            invoice_item = InvoiceItem.objects.create(
                invoice=invoice,
                order_item=row["order_item"],
                chicken_type_snapshot=row["chicken_type"],
                weight_snapshot=row["weight"],
                selling_price_per_kg_snapshot=row["selected_rate"],
                live_rate_snapshot=row["live_rate"],
                yield_percentage_snapshot=row["yield_percentage"],
                subtotal_snapshot=row["subtotal"]
            )

            invoice_items.append({
                "chicken_type": invoice_item.chicken_type_snapshot,
                "weight": float(invoice_item.weight_snapshot),
                "live_rate": float(row["live_rate"]),
                "yield_percentage": (
                    float(row["yield_percentage"])
                    if row["yield_percentage"] is not None
                    else None
                ),
                "meat_rate": (
                    float(row["meat_rate"])
                    if row["meat_rate"] is not None
                    else None
                ),
                "selected_rate": float(row["selected_rate"]),
                "subtotal": float(row["subtotal"])
            })

        return JsonResponse({
            "success": True,
            "message": "Invoice generated successfully.",
            "invoice": {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "order_id": order.id,
                "pricing_mode": invoice.pricing_mode,
                "pricing_date": str(invoice.pricing_date),
                "items": invoice_items,
                "subtotal": float(subtotal),
                "gst_type": gst_type,
                "gst_input": float(gst_input),
                "gst_amount": float(calculated_gst_amount),
                "total_amount": float(total_amount),
                "advance_used": float(advance_used),
                "remaining_amount": float(remaining_amount),
                "status": status
            }
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": str(e)
        }, status=500)


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
        return JsonResponse(
            {"success": False, "message": "GET method required."},
            status=405,
        )

    from datetime import timedelta

    from django.utils import timezone

    today = timezone.localdate()
    start_date = today - timedelta(days=29)
    zero = Decimal("0.00")

    customers = Customer.objects.filter(
        status="active"
    ).order_by("customer_name")

    data = []

    for c in customers:
        # Use the same scoring logic as the Admin page.
        score = c.performance_score
        category = c.performance_category

        # All invoices for this customer's current outstanding balance.
        invoices = list(
            Invoice.objects.filter(
                order__customer=c
            ).prefetch_related("payments")
        )

        outstanding_balance = zero

        for invoice in invoices:
            outstanding_balance += max(
                zero,
                invoice.remaining_amount,
            )

        # Purchases during the last 30 calendar days.
        recent_invoices = [
            invoice
            for invoice in invoices
            if start_date <= timezone.localdate(
                invoice.created_at
            ) <= today
        ]

        recent_purchases = sum(
            (invoice.total_amount for invoice in recent_invoices),
            zero,
        )

        recent_paid = sum(
            (
                max(
                    zero,
                    invoice.total_amount - invoice.remaining_amount,
                )
                for invoice in recent_invoices
            ),
            zero,
        )

        payment_performance = (
            (recent_paid / recent_purchases) * Decimal("100")
            if recent_purchases > zero
            else zero
        )

        # Advance balance across all customer transactions.
        total_advances = (
            AdvancePayment.objects.filter(customer=c).aggregate(
                total=Sum("amount")
            )["total"]
            or zero
        )

        total_advance_used = (
            Invoice.objects.filter(
                order__customer=c
            ).aggregate(total=Sum("advance_used"))["total"]
            or zero
        )

        data.append({
            "id": c.id,
            "customer_name": c.customer_name,
            "company_name": c.company_name,
            "phone": c.phone,

            "performance_score": score,
            "performance_category": category,

            "recent_purchases": float(recent_purchases),
            "payment_performance": round(
                float(payment_performance), 2
            ),
            "outstanding_balance": float(outstanding_balance),

            "total_advances": float(total_advances),
            "total_advance_used": float(total_advance_used),
            "advance_balance": float(
                total_advances - total_advance_used
            ),
        })

    return JsonResponse({
        "success": True,
        "customers": data,
    })


def get_dashboard_stats(request):
    if request.method != "GET":
        return JsonResponse({
            "success": False,
            "message": "GET method required."
        }, status=405)

    target_date = request.GET.get("date")

    inv_qs = Invoice.objects.all()
    ord_qs = Order.objects.all()

    if target_date:
        inv_qs = inv_qs.filter(created_at__date=target_date)
        ord_qs = ord_qs.filter(created_at__date=target_date)

    # Total revenue
    total_revenue = (
        inv_qs.aggregate(Sum("total_amount"))["total_amount__sum"]
        or Decimal("0.00")
    )

    # Total orders
    total_orders = ord_qs.count()

    # Outstanding balance
    # remaining_amount is a Python property, not a DB field,
    # so it cannot be used with Sum().
    unpaid_invoices = (
        inv_qs
        .filter(status__in=["Unpaid", "Partial"])
        .prefetch_related("payments")
    )

    outstanding = Decimal("0.00")

    for invoice in unpaid_invoices:
        outstanding += Decimal(str(invoice.remaining_amount))

    # Total active customers
    total_customers = Customer.objects.filter(status="active").count()

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
        return JsonResponse({
            "success": False,
            "message": "GET method required."
        }, status=405)


    target_date_str = request.GET.get('date')
    period = request.GET.get('period', 'Daily')

    # NEW: Custom date range
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')

    invoices = (
        Invoice.objects
        .select_related('order', 'order__customer')
        .prefetch_related('items', 'payments')
        .order_by('-created_at')
    )

    if target_date_str:
        try:
            target_date = timezone.datetime.strptime(
                target_date_str, "%Y-%m-%d"
            ).date()
        except ValueError:
            return JsonResponse({
                "success": False,
                "message": "Invalid date format. Use YYYY-MM-DD."
            }, status=400)
    else:
        target_date = timezone.localdate()

    # Date filtering

    # Date filtering
    if from_date_str or to_date_str:
        # Both dates are required for custom filtering
        if not from_date_str or not to_date_str:
            return JsonResponse({
                "success": False,
                "message": "Both From Date and To Date are required."
            }, status=400)

        try:
            from_date = timezone.datetime.strptime(
                from_date_str, "%Y-%m-%d"
            ).date()

            to_date = timezone.datetime.strptime(
                to_date_str, "%Y-%m-%d"
            ).date()

        except ValueError:
            return JsonResponse({
                "success": False,
                "message": "Invalid date format. Use YYYY-MM-DD."
            }, status=400)

        if from_date > to_date:
            return JsonResponse({
                "success": False,
                "message": "From Date cannot be after To Date."
            }, status=400)

        # Include both start and end dates
        invoices = invoices.filter(
            created_at__date__range=(from_date, to_date)
        )

    elif period == 'Daily':
        invoices = invoices.filter(
            created_at__date=target_date
        )

    elif period == 'Weekly':
        start_of_week = target_date - timedelta(
            days=target_date.weekday()
        )
        end_of_week = start_of_week + timedelta(days=6)

        invoices = invoices.filter(
            created_at__date__range=(
                start_of_week, end_of_week
            )
        )

    elif period == 'Monthly':
        invoices = invoices.filter(
            created_at__year=target_date.year,
            created_at__month=target_date.month
        )


    # Existing summary calculations
    total_revenue = (
        invoices.aggregate(Sum('total_amount'))['total_amount__sum']
        or Decimal('0.00')
    )

    total_orders = invoices.count()

    sales_list = []

    # Customer-wise grouped transactions
    customer_groups = defaultdict(lambda: {
        "customer_code": "",
        "customer_name": "",
        "items": [],
        "receipt": Decimal("0.00"),
        "balance": Decimal("0.00"),
    })


        # Separate invoice reports by pricing mode
    pricing_groups = {
        "live_rate": defaultdict(dict),
        "meat_rate": defaultdict(dict),
        "legacy": defaultdict(dict),
    }

    pricing_totals = {
        mode: {
            "quantity": Decimal("0.00"),
            "total_amount": Decimal("0.00"),
            "paid_amount": Decimal("0.00"),
            "balance_amount": Decimal("0.00"),
        }
        for mode in pricing_groups
    }

    for inv in invoices:
        customer = inv.order.customer
        customer_code = str(customer.id)

        sales_list.append({
            "id": inv.id,  # Numeric invoice database ID
            "invoice_no": inv.invoice_number,
            "customer_id": customer.id,
            "customer": customer.customer_name,
            "created_at": inv.created_at.isoformat(),
            "date": inv.created_at.strftime(
                "%d %b %Y, %I:%M %p"
            ),
            "amount": float(inv.total_amount),
            "status": inv.status,
        })
        group = customer_groups[customer.id]

        group["customer_code"] = customer_code
        group["customer_name"] = customer.customer_name

        # Applied advance + payments received against this invoice
        invoice_payments = sum(
            (payment.amount for payment in inv.payments.all()),
            Decimal("0.00")
        )

        group["receipt"] += (
            inv.advance_used + invoice_payments
        )

        group["balance"] += inv.remaining_amount

        # Invoice item details
        for item in inv.items.all():
            quantity = item.weight_snapshot or Decimal("0.00")
            rate = (
                item.selling_price_per_kg_snapshot
                or Decimal("0.00")
            )

            amount = item.subtotal_snapshot

            if amount is None:
                amount = quantity * rate

            group["items"].append({
                "item_name": item.chicken_type_snapshot,
                "quantity": float(quantity),
                "rate": float(rate),
                "amount": float(amount),
                "invoice_no": inv.invoice_number,
            })



                    # NEW: Separate Live Rate and Meat Rate purchases
        mode = inv.pricing_mode or "legacy"

        if mode not in pricing_groups:
            mode = "legacy"

        mode_customers = pricing_groups[mode]

        if customer.id not in mode_customers:
            mode_customers[customer.id] = {
                "customer_code": customer_code,
                "customer_name": customer.customer_name,
                "items": [],
                "quantity": Decimal("0.00"),
                "total_amount": Decimal("0.00"),
                "paid_amount": Decimal("0.00"),
                "balance_amount": Decimal("0.00"),
            }

        mode_group = mode_customers[customer.id]

        paid = (
            (inv.advance_used or Decimal("0.00"))
            + invoice_payments
        )

        invoice_total = inv.total_amount or Decimal("0.00")
        balance = invoice_total - paid

        # Financial values are counted once per invoice
        mode_group["total_amount"] += invoice_total
        mode_group["paid_amount"] += paid
        mode_group["balance_amount"] += balance

        pricing_totals[mode]["total_amount"] += invoice_total
        pricing_totals[mode]["paid_amount"] += paid
        pricing_totals[mode]["balance_amount"] += balance

        # Add every meat category purchased
        for item in inv.items.all():
            quantity = item.weight_snapshot or Decimal("0.00")
            rate = (
                item.selling_price_per_kg_snapshot
                or Decimal("0.00")
            )

            amount = item.subtotal_snapshot
            if amount is None:
                amount = quantity * rate

            mode_group["items"].append({
                "item_name": item.chicken_type_snapshot,
                "quantity": float(quantity),
                "rate": float(rate),
                "amount": float(amount),
                "invoice_no": inv.invoice_number,
            })

            mode_group["quantity"] += quantity
            pricing_totals[mode]["quantity"] += quantity

    customer_transactions = []

    for group in customer_groups.values():
        group["receipt"] = float(group["receipt"])
        group["balance"] = float(group["balance"])
        customer_transactions.append(group)

    # Existing revenue trend calculation
    revenue_trend = []

    if period == 'Monthly':
        for i in range(5, -1, -1):
            month_start = (
                target_date.replace(day=1) - timedelta(days=30 * i)
            ).replace(day=1)

            rev = Invoice.objects.filter(
                created_at__year=month_start.year,
                created_at__month=month_start.month
            ).aggregate(
                Sum('total_amount')
            )['total_amount__sum'] or Decimal('0.00')

            revenue_trend.append({
                "day": month_start.strftime("%b"),
                "revenue": float(rev)
            })

    elif period == 'Weekly':
        start_of_week = target_date - timedelta(
            days=target_date.weekday()
        )

        for i in range(6, -1, -1):
            w_start = start_of_week - timedelta(weeks=i)
            w_end = w_start + timedelta(days=6)

            rev = Invoice.objects.filter(
                created_at__date__gte=w_start,
                created_at__date__lte=w_end
            ).aggregate(
                Sum('total_amount')
            )['total_amount__sum'] or Decimal('0.00')

            revenue_trend.append({
                "day": w_start.strftime("%d %b"),
                "revenue": float(rev)
            })

    else:
        for i in range(6, -1, -1):
            day = target_date - timedelta(days=i)

            rev = Invoice.objects.filter(
                created_at__date=day
            ).aggregate(
                Sum('total_amount')
            )['total_amount__sum'] or Decimal('0.00')

            revenue_trend.append({
                "day": day.strftime("%a"),
                "revenue": float(rev)
            })
    def serialize_pricing_groups(mode):
        result = []

        for customer_data in pricing_groups[mode].values():
            result.append({
                **customer_data,
                "quantity": float(customer_data["quantity"]),
                "total_amount": float(customer_data["total_amount"]),
                "paid_amount": float(customer_data["paid_amount"]),
                "balance_amount": float(customer_data["balance_amount"]),
            })

        return result

    def serialize_pricing_totals(mode):
        return {
            key: float(value)
            for key, value in pricing_totals[mode].items()
        }

    report_summary = {
        "live_rate": serialize_pricing_totals("live_rate"),
        "meat_rate": serialize_pricing_totals("meat_rate"),
        "legacy": serialize_pricing_totals("legacy"),
    }

    return JsonResponse({
        "success": True,

        # Existing fields - keep frontend working
        "sales": sales_list,
        "customer_transactions": customer_transactions,
        "total_revenue": float(total_revenue),
        "total_orders": total_orders,
        "revenue_trend": revenue_trend,

        # NEW: Separated purchases
        "live_rate_purchases": serialize_pricing_groups(
            "live_rate"
        ),
        "meat_rate_purchases": serialize_pricing_groups(
            "meat_rate"
        ),
        "legacy_purchases": serialize_pricing_groups(
            "legacy"
        ),

        # NEW: Section totals
        "summary": report_summary,
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



from datetime import date, datetime


PDF_SORT_OPTIONS = {
    "newest",
    "oldest",
    "az",
    "za",
    "high",
    "low",
}


def sort_pdf_records(
    records,
    sort_by="newest",
    name_key="customer",
    date_key="date",
    amount_key="amount",
):
    """
    Sort report records without modifying original data.

    records: list of dictionaries containing:
        customer/name, date, amount, and PDF row data.

    Does not change invoice or payment calculations.
    """

    sort_by = (
        sort_by
        if sort_by in PDF_SORT_OPTIONS
        else "newest"
    )

    result = list(records)

    def name_value(record):
        return str(
            record.get(name_key) or ""
        ).casefold()

    def date_value(record):
        value = record.get(date_key)

        if isinstance(value, datetime):
            return value.date().toordinal()

        if isinstance(value, date):
            return value.toordinal()

        if isinstance(value, str):
            try:
                return date.fromisoformat(
                    value[:10]
                ).toordinal()
            except ValueError:
                pass

        return 0

    def amount_value(record):
        value = record.get(amount_key, 0)

        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0.00")

    if sort_by == "az":
        result.sort(key=name_value)

    elif sort_by == "za":
        result.sort(
            key=name_value,
            reverse=True
        )

    elif sort_by == "oldest":
        result.sort(key=date_value)

    elif sort_by == "newest":
        result.sort(
            key=date_value,
            reverse=True
        )

    elif sort_by == "high":
        result.sort(
            key=amount_value,
            reverse=True
        )

    elif sort_by == "low":
        result.sort(key=amount_value)

    return result



def export_outstanding_pdf(request):
    if request.method != "GET":
        return HttpResponse(
            "GET method required.",
            status=405
        )

    sort_by = request.GET.get(
        "sort_by", "newest"
    )

    invoices = (
        Invoice.objects
        .select_related(
            "order",
            "order__customer"
        )
        .exclude(status="Paid")
        .order_by("id")
    )

    grouped = {}

    for invoice in invoices:
        balance = invoice.remaining_amount

        if balance <= Decimal("0.00"):
            continue

        customer = invoice.order.customer
        customer_id = customer.id

        delivery_date = invoice.order.delivery_date

        if customer_id not in grouped:
            grouped[customer_id] = {
                "customer": customer.customer_name,
                "company": customer.company_name,
                "invoice_count": 0,
                "amount": Decimal("0.00"),
                "date": delivery_date,
                "invoice_numbers": [],
            }

        group = grouped[customer_id]

        group["invoice_count"] += 1
        group["amount"] += balance

        group["invoice_numbers"].append(
            str(invoice.invoice_number)
        )

        # Latest pending invoice delivery date
        if delivery_date and (
            group["date"] is None
            or delivery_date > group["date"]
        ):
            group["date"] = delivery_date

    records = sort_pdf_records(
        grouped.values(),
        sort_by=sort_by,
        name_key="customer",
        date_key="date",
        amount_key="amount",
    )

    headers = [
        "Customer",
        "Pending Invoices",
        "Outstanding",
        "Latest Delivery",
    ]

    rows = []

    total_outstanding = Decimal("0.00")
    total_invoices = 0

    for record in records:
        total_outstanding += record["amount"]
        total_invoices += record["invoice_count"]

        rows.append([
            str(record["customer"]),
            str(record["invoice_count"]),
            f"Rs.{record['amount']:.2f}",
            (
                record["date"].strftime("%d %b %Y")
                if record["date"]
                else "-"
            ),
        ])

    rows.append([
        "GRAND TOTAL",
        str(total_invoices),
        f"Rs.{total_outstanding:.2f}",
        "",
    ])

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        'attachment; filename="Outstanding_Payments.pdf"'
    )

    return _generate_table_pdf(
        response,
        "Customer-wise Outstanding Payments",
        headers,
        rows
    )



def export_advances_pdf(request):
    if request.method != "GET":
        return HttpResponse(
            "GET method required.",
            status=405
        )

    sort_by = request.GET.get(
        "sort_by", "newest"
    )

    advances = (
        AdvancePayment.objects
        .select_related("customer")
        .order_by("-created_at", "-id")
    )

    records = []

    for advance in advances:
        records.append({
            "customer": advance.customer.customer_name,
            "date": advance.created_at,
            "amount": advance.amount,
            "row": [
                str(advance.advance_number),
                advance.customer.customer_name,
                f"Rs.{advance.amount:.2f}",
                advance.created_at.strftime(
                    "%d %b %Y"
                ),
                advance.note or "",
            ],
        })

    sorted_records = sort_pdf_records(
        records,
        sort_by=sort_by,
    )

    rows = [
        record["row"]
        for record in sorted_records
    ]

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        'attachment; filename="Advances.pdf"'
    )

    return _generate_table_pdf(
        response,
        "Customer Advances",
        [
            "Advance ID",
            "Customer",
            "Amount",
            "Date",
            "Note",
        ],
        rows
    )



def export_balances_pdf(request):
    if request.method != "GET":
        return HttpResponse(
            "GET method required.",
            status=405
        )

    sort_by = request.GET.get(
        "sort_by", "high"
    )

    customers = Customer.objects.all()

    records = []

    for customer in customers:
        received = (
            AdvancePayment.objects
            .filter(customer=customer)
            .aggregate(Sum("amount"))["amount__sum"]
            or Decimal("0.00")
        )

        consumed = (
            Invoice.objects
            .filter(order__customer=customer)
            .aggregate(Sum("advance_used"))[
                "advance_used__sum"
            ]
            or Decimal("0.00")
        )

        if received <= Decimal("0.00"):
            continue

        remaining = received - consumed

        utilization = (
            consumed / received
        ) * Decimal("100.00")

        latest_advance = (
            AdvancePayment.objects
            .filter(customer=customer)
            .order_by("-created_at")
            .first()
        )

        records.append({
            "customer": customer.customer_name,
            "date": (
                latest_advance.created_at
                if latest_advance
                else None
            ),
            "amount": remaining,
            "row": [
                customer.customer_name,
                f"Rs.{received:.2f}",
                f"Rs.{consumed:.2f}",
                f"Rs.{remaining:.2f}",
                f"{utilization:.1f}%",
            ],
        })

    sorted_records = sort_pdf_records(
        records,
        sort_by=sort_by,
    )

    rows = [
        record["row"]
        for record in sorted_records
    ]

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        'attachment; filename="Advance_Balances.pdf"'
    )

    return _generate_table_pdf(
        response,
        "Advance Balances",
        [
            "Customer",
            "Received",
            "Consumed",
            "Remaining",
            "Utilization",
        ],
        rows
    )



def export_sales_report_pdf(request):
    if request.method != "GET":
        return HttpResponse(
            "GET method required.",
            status=405
        )

    sort_by = request.GET.get(
        "sort_by", "newest"
    )

    invoices = (
        Invoice.objects
        .select_related(
            "order",
            "order__customer"
        )
        .order_by("-created_at", "-id")
    )

    records = []

    for invoice in invoices:
        records.append({
            "customer": (
                invoice.order.customer.customer_name
            ),
            "date": invoice.created_at,
            "amount": invoice.total_amount,
            "row": [
                str(invoice.invoice_number),
                invoice.order.customer.customer_name,
                invoice.created_at.strftime(
                    "%d %b %Y"
                ),
                f"Rs.{invoice.total_amount:.2f}",
                invoice.status,
            ],
        })

    sorted_records = sort_pdf_records(
        records,
        sort_by=sort_by,
    )

    rows = [
        record["row"]
        for record in sorted_records
    ]

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        'attachment; filename="Sales_Report.pdf"'
    )

    return _generate_table_pdf(
        response,
        "Sales Report",
        [
            "Invoice No",
            "Customer",
            "Date",
            "Amount",
            "Status",
        ],
        rows
    )



def export_purchase_orders_pdf(request):
    if request.method != "GET":
        return HttpResponse(
            "GET method required.",
            status=405
        )

    sort_by = request.GET.get(
        "sort_by", "newest"
    )

    orders = (
        Order.objects
        .select_related("customer")
        .prefetch_related("items")
        .filter(status="Ready")
        .order_by("-created_at", "-id")
    )

    records = []


    for order in orders:
        order_items = list(order.items.all())

        items_summary = " + ".join(
            str(item.chicken_type)
            for item in order_items
        )

        # Calculate total weight from OrderItem records
        total_weight = sum(
            (
                Decimal(str(item.weight or 0))
                for item in order_items
            ),
            Decimal("0.00")
        )

        records.append({
            "customer": order.customer.customer_name,
            "date": order.created_at,
            "amount": None,
            "row": [
                str(order.order_number),
                order.customer.customer_name,
                items_summary or "-",
                f"{total_weight:.2f}",
                order.status,
            ],
        })

    # Amount sorting is not meaningful for Orders.
    if sort_by in ("high", "low"):
        sort_by = "newest"

    sorted_records = sort_pdf_records(
        records,
        sort_by=sort_by,
    )

    rows = [
        record["row"]
        for record in sorted_records
    ]

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        'attachment; filename="Purchase_Orders.pdf"'
    )

    return _generate_table_pdf(
        response,
        "Pending Purchase Orders",
        [
            "Order No",
            "Customer",
            "Items",
            "Total Weight (Kg)",
            "Status",
        ],
        rows
    )


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



# ==========================================================
# CUSTOMER-WISE OUTSTANDING PAYMENT
# ==========================================================

@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([
    IsAuthenticated,
    CanManageCustomerPayments,
])
def get_customer_outstanding(request):
    """
    Return all pending invoices, grouped customer-wise.

    Intentionally does not filter by date, because
    a customer may have unpaid invoices from many days.
    """

    invoices = (
        Invoice.objects
        .select_related("order", "order__customer")
        .exclude(status="Paid")
        .order_by(
            "order__customer_id",
            "order__delivery_date",
            "id"
        )
    )

    customers = {}
    total_outstanding = Decimal("0.00")
    total_pending_invoices = 0

    for invoice in invoices:
        balance = invoice.remaining_amount

        if balance <= Decimal("0.00"):
            continue

        customer = invoice.order.customer
        customer_id = customer.id

        if customer_id not in customers:
            customers[customer_id] = {
                "customer_id": customer_id,
                "customer": customer.customer_name,
                "company": customer.company_name,
                "total_outstanding": Decimal("0.00"),
                "invoice_count": 0,
                "invoices": [],
            }

        group = customers[customer_id]

        group["total_outstanding"] += balance
        group["invoice_count"] += 1

        group["invoices"].append({
            "id": invoice.invoice_number,
            "invoice_id": invoice.id,
            "customer": customer.customer_name,
            "due_date": invoice.order.delivery_date.strftime(
                "%d %b %Y"
            ),
            "delivery_date": invoice.order.delivery_date.isoformat(),
            "total": float(invoice.total_amount),
            "advance": float(invoice.advance_used),
            "balance": float(balance),
            "status": invoice.status,
        })

        total_outstanding += balance
        total_pending_invoices += 1

    result = []

    for group in customers.values():
        group["total_outstanding"] = float(
            group["total_outstanding"]
        )

        result.append(group)

    result.sort(
        key=lambda c: c["total_outstanding"],
        reverse=True
    )

    return JsonResponse({
        "success": True,
        "customers": result,
        "stats": {
            "total_outstanding": float(total_outstanding),
            "pending_customers": len(result),
            "pending_invoices": total_pending_invoices,
        },
    })


# ==========================================================
# RECORD ONE PAYMENT AGAINST MULTIPLE INVOICES
# ==========================================================

@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([
    IsAuthenticated,
    CanManageCustomerPayments,
])
def record_customer_bulk_payment(request, customer_id):
    """
    Allocate a single customer payment across all pending
    invoices, oldest delivery date first.

    Uses row locks and a database transaction to prevent
    concurrent overpayments and partial saves.
    """

    data = request.data

    amount_raw = data.get("amount")
    payment_method = data.get(
        "payment_method",
        "Cash"
    )

    reference_no = str(
        data.get("reference_no") or ""
    ).strip()

    note = str(
        data.get("note") or ""
    ).strip()

    if amount_raw is None:
        return JsonResponse({
            "success": False,
            "message": "Payment amount is required."
        }, status=400)

    try:
        amount = Decimal(str(amount_raw))

        if not amount.is_finite():
            raise InvalidOperation

        if amount <= 0:
            return JsonResponse({
                "success": False,
                "message": "Payment must be greater than zero."
            }, status=400)

        if amount.as_tuple().exponent < -2:
            return JsonResponse({
                "success": False,
                "message": "Only two decimal places are allowed."
            }, status=400)

        amount = amount.quantize(Decimal("0.01"))

    except (InvalidOperation, ValueError, TypeError):
        return JsonResponse({
            "success": False,
            "message": "Invalid payment amount."
        }, status=400)

    allowed_methods = {
        "Cash",
        "UPI",
        "Bank Transfer",
        "Cheque",
    }

    if payment_method not in allowed_methods:
        return JsonResponse({
            "success": False,
            "message": "Invalid payment method."
        }, status=400)

    if len(reference_no) > 100:
        return JsonResponse({
            "success": False,
            "message": "Reference number is too long."
        }, status=400)

    try:
        with transaction.atomic():

            # Lock customer first to serialize customer-wise
            # payments made through this endpoint.
            customer = (
                Customer.objects
                .select_for_update()
                .get(pk=customer_id)
            )

            # Lock all invoices for this customer,
            # consistently ordered by primary key.
            locked_invoices = list(
                Invoice.objects
                .select_for_update()
                .filter(order__customer_id=customer.id)
                .order_by("id")
            )

            pending = []

            for invoice in locked_invoices:
                balance = invoice.remaining_amount

                if balance > Decimal("0.00"):
                    pending.append({
                        "invoice": invoice,
                        "balance": balance,
                    })

            # Oldest invoice first, using delivery date.
            pending.sort(
                key=lambda entry: (
                    entry["invoice"].order.delivery_date,
                    entry["invoice"].id,
                )
            )

            total_due = sum(
                (
                    entry["balance"]
                    for entry in pending
                ),
                Decimal("0.00")
            )

            if total_due <= 0:
                return JsonResponse({
                    "success": False,
                    "message": "No pending invoices for this customer."
                }, status=400)

            if amount > total_due:
                return JsonResponse({
                    "success": False,
                    "message": (
                        f"Payment exceeds customer outstanding "
                        f"amount of ₹{total_due:.2f}."
                    )
                }, status=400)

            remaining_payment = amount
            allocations = []

            for entry in pending:
                if remaining_payment <= 0:
                    break

                invoice = entry["invoice"]
                invoice_balance = entry["balance"]

                allocated = min(
                    remaining_payment,
                    invoice_balance
                )

                payment = InvoicePayment.objects.create(
                    invoice=invoice,
                    amount=allocated,
                    payment_method=payment_method,
                    reference_no=reference_no,
                    note=note,
                )

                invoice.update_status()

                allocations.append({
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "payment_id": payment.id,
                    "paid": float(allocated),
                    "new_balance": float(
                        invoice.remaining_amount
                    ),
                    "new_status": invoice.status,
                })

                remaining_payment -= allocated

            return JsonResponse({
                "success": True,
                "message": "Customer payment recorded successfully.",
                "customer_id": customer.id,
                "customer": customer.customer_name,
                "total_paid": float(amount),
                "remaining_outstanding": float(
                    total_due - amount
                ),
                "allocations": allocations,
            })

    except Customer.DoesNotExist:
        return JsonResponse({
            "success": False,
            "message": "Customer not found."
        }, status=404)

    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Customer bulk payment failed"
        )

        return JsonResponse({
            "success": False,
            "message": "Unable to record payment."
        }, status=500)


from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from collections import defaultdict
from decimal import Decimal
from django.utils.dateparse import parse_date
from django.db.models import Q
from Admin.models import Invoice

def get_balance_amount_report(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET method required."}, status=405)

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    period = request.GET.get("period", "Daily")

    invoices = Invoice.objects.select_related("order__customer").all().order_by("order__customer__name")

    if start_date:
        invoices = invoices.filter(created_at__date__gte=parse_date(start_date))
    if end_date:
        invoices = invoices.filter(created_at__date__lte=parse_date(end_date))

    customer_map = defaultdict(lambda: {
        "customer_id": None,
        "customer_name": "",
        "phone_number": "",
        "invoice_count": 0,
        "total_invoiced": Decimal("0.00"),
        "total_paid": Decimal("0.00"),
        "total_balance": Decimal("0.00"),
    })

    for invoice in invoices:
        customer = getattr(invoice.order, "customer", None)
        if not customer:
            continue

        key = customer.id
        row = customer_map[key]

        row["customer_id"] = customer.id
        row["customer_name"] = customer.name
        row["phone_number"] = getattr(customer, "phone", "") or getattr(customer, "mobile", "") or ""
        row["invoice_count"] += 1
        row["total_invoiced"] += Decimal(str(invoice.total_amount or 0))
        row["total_paid"] += Decimal(str(getattr(invoice, "paid_amount", 0) or 0))
        row["total_balance"] += Decimal(str(getattr(invoice, "balance_amount", 0) or 0))

    results = []
    for row in customer_map.values():
        if row["total_balance"] <= 0:
            status = "Paid"
        elif row["total_paid"] <= 0:
            status = "Unpaid"
        else:
            status = "Partial"

        results.append({
            "customer_id": row["customer_id"],
            "customer_name": row["customer_name"],
            "phone_number": row["phone_number"],
            "invoice_count": row["invoice_count"],
            "total_invoiced": float(row["total_invoiced"]),
            "total_paid": float(row["total_paid"]),
            "total_balance": float(row["total_balance"]),
            "status": status,
        })

    grand_total_invoiced = sum(item["total_invoiced"] for item in results)
    grand_total_paid = sum(item["total_paid"] for item in results)
    grand_total_balance = sum(item["total_balance"] for item in results)

    return JsonResponse({
        "success": True,
        "period": period,
        "results": results,
        "summary": {
            "total_customers": len(results),
            "total_invoiced": grand_total_invoiced,
            "total_paid": grand_total_paid,
            "total_balance": grand_total_balance,
        }
    })



from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def export_balance_amount_report_pdf(request):
    report_response = get_balance_amount_report(request)
    data = json.loads(report_response.content.decode("utf-8"))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Balance_Amount_Report.pdf"'

    doc = SimpleDocTemplate(response, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Balance Amount Details Report", styles["Title"]))
    story.append(Spacer(1, 12))

    table_data = [[
        "Customer Name",
        "Phone Number",
        "Invoice Count",
        "Total Invoiced",
        "Total Paid",
        "Total Balance",
        "Status"
    ]]

    for row in data.get("results", []):
        table_data.append([
            row["customer_name"],
            row["phone_number"],
            str(row["invoice_count"]),
            f'Rs. {row["total_invoiced"]:.2f}',
            f'Rs. {row["total_paid"]:.2f}',
            f'Rs. {row["total_balance"]:.2f}',
            row["status"],
        ])

    summary = data.get("summary", {})
    table_data.append([
        "TOTAL",
        "",
        str(summary.get("total_customers", 0)),
        f'Rs. {summary.get("total_invoiced", 0):.2f}',
        f'Rs. {summary.get("total_paid", 0):.2f}',
        f'Rs. {summary.get("total_balance", 0):.2f}',
        "",
    ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4B5EAA")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DCE6F8")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    story.append(table)
    doc.build(story)
    return response




from django.utils.dateparse import parse_date
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([
    IsAuthenticated,
    CanManageCustomerPayments,
])
def get_balance_amount_report(request):
    """
    Customer-wise balance details.

    Invoiced = sum of invoice totals
    Paid = advance used + direct invoice payments
    Balance = invoiced - paid

    Date filters select invoices by creation date.
    Payments represent their current recorded state.
    """

    period = request.GET.get("period", "All")
    from_date_str = request.GET.get("from_date")
    to_date_str = request.GET.get("to_date")

    allowed_periods = {
        "All",
        "Daily",
        "Weekly",
        "Monthly",
    }

    if period not in allowed_periods:
        return JsonResponse({
            "success": False,
            "message": "Invalid report period."
        }, status=400)

    if bool(from_date_str) != bool(to_date_str):
        return JsonResponse({
            "success": False,
            "message": "Both dates are required."
        }, status=400)

    zero = Decimal("0.00")
    today = timezone.localdate()

    invoices = (
        Invoice.objects
        .select_related(
            "order",
            "order__customer",
        )
        .annotate(
            direct_paid=Sum("payments__amount")
        )
        .order_by(
            "order__customer__customer_name",
            "id",
        )
    )

    if from_date_str and to_date_str:
        from_date = parse_date(from_date_str)
        to_date = parse_date(to_date_str)

        if not from_date or not to_date:
            return JsonResponse({
                "success": False,
                "message": "Invalid date format. Use YYYY-MM-DD."
            }, status=400)

        if from_date > to_date:
            return JsonResponse({
                "success": False,
                "message": "From Date cannot exceed To Date."
            }, status=400)

        invoices = invoices.filter(
            created_at__date__range=(
                from_date,
                to_date,
            )
        )

    elif period == "Daily":
        invoices = invoices.filter(
            created_at__date=today
        )

    elif period == "Weekly":
        week_start = today - timedelta(
            days=today.weekday()
        )

        invoices = invoices.filter(
            created_at__date__range=(
                week_start,
                today,
            )
        )

    elif period == "Monthly":
        month_start = today.replace(day=1)

        invoices = invoices.filter(
            created_at__date__range=(
                month_start,
                today,
            )
        )

    customer_map = {}

    for invoice in invoices:
        customer = invoice.order.customer

        if customer.id not in customer_map:
            customer_map[customer.id] = {
                "customer_id": customer.id,
                "customer_name": customer.customer_name,
                "phone_number": customer.phone or "",
                "invoice_count": 0,
                "total_invoiced": zero,
                "total_paid": zero,
                "total_balance": zero,
                "last_invoice_date": None,
            }

        row = customer_map[customer.id]

        invoiced = (
            invoice.total_amount or zero
        )

        advance_used = (
            invoice.advance_used or zero
        )

        direct_paid = (
            invoice.direct_paid or zero
        )

        # Never record an amount greater than the
        # invoice total as settled for reporting.
        paid = min(
            invoiced,
            max(zero, advance_used + direct_paid)
        )

        balance = max(
            zero,
            invoiced - paid
        )

        row["invoice_count"] += 1
        row["total_invoiced"] += invoiced
        row["total_paid"] += paid
        row["total_balance"] += balance

        created_date = timezone.localdate(
            invoice.created_at
        )

        if (
            row["last_invoice_date"] is None
            or created_date > row["last_invoice_date"]
        ):
            row["last_invoice_date"] = created_date

    results = []

    for row in customer_map.values():
        paid = row["total_paid"]
        balance = row["total_balance"]

        if balance <= zero:
            status = "Paid"
        elif paid > zero:
            status = "Partial"
        else:
            status = "Unpaid"

        results.append({
            "customer_id": row["customer_id"],
            "customer_name": row["customer_name"],
            "phone_number": row["phone_number"],
            "invoice_count": row["invoice_count"],
            "total_invoiced": float(
                row["total_invoiced"]
            ),
            "total_paid": float(
                row["total_paid"]
            ),
            "total_balance": float(
                row["total_balance"]
            ),
            "last_invoice_date": (
                row["last_invoice_date"].isoformat()
                if row["last_invoice_date"]
                else None
            ),
            "status": status,
        })

    results.sort(
        key=lambda item: item["customer_name"].casefold()
    )

    summary = {
        "total_customers": len(results),
        "total_invoices": sum(
            row["invoice_count"]
            for row in results
        ),
        "total_invoiced": round(
            sum(
                row["total_invoiced"]
                for row in results
            ), 2
        ),
        "total_paid": round(
            sum(
                row["total_paid"]
                for row in results
            ), 2
        ),
        "total_balance": round(
            sum(
                row["total_balance"]
                for row in results
            ), 2
        ),
    }

    return JsonResponse({
        "success": True,
        "period": period,
        "results": results,
        "summary": summary,
    })
