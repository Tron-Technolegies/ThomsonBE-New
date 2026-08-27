from django.shortcuts import render

# Create your views here.
import json

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Customer


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
                "updated_at": customer.updated_at
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