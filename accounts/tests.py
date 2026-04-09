from django.test import TestCase
from django.urls import reverse
from .models import User

class AccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123', role='User')
        self.admin = User.objects.create_user(username='adminuser', password='password123', role='Admin')

    def test_user_creation(self):
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.role, 'User')

    def test_login_redirect(self):
        # Admin login
        self.client.login(username='adminuser', password='password123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.client.logout()
        
        # User login
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('user_dashboard'))
        self.client.logout()

    def test_admin_decorators(self):
        # User accessing admin dashboard
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
