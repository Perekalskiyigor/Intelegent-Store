from django.test import TestCase
from django.db import connection

class DbSmokeTest(TestCase):
    def test_select_1(self):
        with connection.cursor() as cur:
            cur.execute("SELECT 1;")
            self.assertEqual(cur.fetchone()[0], 1)
