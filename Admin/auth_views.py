from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from django.contrib.auth.models import User
from .models import StaffProfile
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims
        token['username'] = user.username
        token['email'] = user.email
        
        if hasattr(user, 'staff_profile'):
            token['role'] = user.staff_profile.role
        else:
            if user.is_superuser:
                token['role'] = 'admin'
            else:
                token['role'] = 'unknown'

        return token

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_staff_list(request):
    staff_profiles = StaffProfile.objects.all().select_related('user')
    data = []
    for profile in staff_profiles:
        data.append({
            'id': profile.user.id,
            'username': profile.user.username,
            'email': profile.user.email,
            'role': profile.role,
            'phone': profile.phone,
            'is_active': profile.user.is_active,
            'created_at': profile.created_at
        })
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_staff(request):
    data = request.data
    try:
        # Create user
        user = User.objects.create_user(
            username=data['username'],
            email=data.get('email', ''),
            password=data['password']
        )
        
        # Create profile
        StaffProfile.objects.create(
            user=user,
            role=data.get('role', 'cutting'),
            phone=data.get('phone', '')
        )
        
        return Response({'message': 'Staff created successfully'}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_staff(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        data = request.data
        
        user.username = data.get('username', user.username)
        user.email = data.get('email', user.email)
        
        if 'password' in data and data['password']:
            user.set_password(data['password'])
            
        if 'is_active' in data:
            user.is_active = data['is_active']
            
        user.save()
        
        profile = user.staff_profile
        profile.role = data.get('role', profile.role)
        profile.phone = data.get('phone', profile.phone)
        profile.save()
        
        return Response({'message': 'Staff updated successfully'})
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_staff(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        if user.is_superuser:
            return Response({'error': 'Cannot delete superuser'}, status=status.HTTP_400_BAD_REQUEST)
            
        user.delete()
        return Response({'message': 'Staff deleted successfully'})
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
