from django.http import HttpRequest
from django.test import TestCase, RequestFactory

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer

import boto3
from moto import mock_s3
from unittest.mock import patch
import json


from audit_logging.middleware import EgressAuditLogMiddleware
from audit_logging.utils import AuditableResponse

from django.contrib.auth.models import AnonymousUser, User


class UserSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"


class AuditLogTestCase(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

        self.user = User.objects.create(
            username="UserUser",
            email="user@user.com",
            first_name="Us",
            last_name="er",
            password="password",
        )

        self.serializer = UserSerializer(User.objects.all())

        self.auditable_response = AuditableResponse(
            auditable_serializers=[self.serializer]
        )

        self.raw_response = Response(
            data={"serializer_member": {"serializer": self.serializer}}
        )

        self.raw_response_without_serializer = Response(
            data={"no_serializer_here": "none at all"}
        )

        self.s3_log_config = {
            "log_type": "s3",
            "s3_bucket": "unittest-access-audit-logs",
        }

        self.std_out_log_config = {"log_type": "std_out"}

    @mock_s3
    def test_log_emission_auditable_response_with_s3(
        self,
    ):
        self._run_middleware_test_with_s3(
            response=self.auditable_response,
            user=self.user,
            expected_user_name=self.user.username,
        )

    @mock_s3
    def test_log_emission_raw_response_with_s3(self):
        self._run_middleware_test_with_s3(
            response=self.raw_response,
            user=self.user,
            expected_user_name=self.user.username,
        )

    @mock_s3
    def test_log_emission_unauthed_user_with_s3(self):
        self._run_middleware_test_with_s3(
            response=self.auditable_response,
            user=AnonymousUser(),
            expected_user_name="Anonymous",
        )

    @patch(
        "audit_logging.middleware.EgressAuditLogMiddleware._get_user_identifying_information"
    )
    def test_exception_does_not_break_execution(self, get_user_info):
        with self.settings(EGRESS_LOGGING_CONFIGURATION=self.s3_log_config):
            get_user_info.side_effect = Exception("Mock Exception")

            req = self.request_factory.get(path="somepath", HTTP_X_REAL_IP="8.8.8.8")
            req.user = self.user

            middleware = EgressAuditLogMiddleware(
                get_response=lambda request: self.raw_response
            )
            raw_req = HttpRequest()
            raw_req.path = "some/path"
            req = Request(request=raw_req)
            res = middleware.__call__(req)
            self.assertEqual(res, self.raw_response)

    @mock_s3
    def test_s3_exception_does_not_break_execution(self):
        with self.settings(EGRESS_LOGGING_CONFIGURATION=self.s3_log_config):
            req = self.request_factory.get(path="somepath", HTTP_X_REAL_IP="8.8.8.8")
            req.user = self.user

            conn = boto3.resource("s3", region_name="us-east-1")

            # give the bucket the wrong name to induce an exception
            conn.create_bucket(Bucket="not-the-right-bucket")

            middleware = EgressAuditLogMiddleware(
                get_response=lambda request: self.raw_response
            )
            raw_req = HttpRequest()
            raw_req.path = "some/path"
            req = Request(request=raw_req)
            req.user = self.user
            res = middleware.__call__(req)
            self.assertEqual(res, self.raw_response)

    def _run_middleware_test_with_s3(self, response, user, expected_user_name):
        with self.settings(EGRESS_LOGGING_CONFIGURATION=self.s3_log_config):
            req = self.request_factory.get(path="somepath", HTTP_X_REAL_IP="8.8.8.8")
            req.user = user

            conn = boto3.resource("s3", region_name="us-east-1")
            conn.create_bucket(Bucket=self.s3_log_config["s3_bucket"])

            middleware = EgressAuditLogMiddleware(get_response=lambda request: response)

            res = middleware.__call__(req)

            self.assertEqual(res, response)

            bucket = conn.Bucket(self.s3_log_config["s3_bucket"])

            objs = list(bucket.objects.all())
            self.assertEqual(len(objs), 1)

            blob = blob = json.loads(
                conn.Object(self.s3_log_config["s3_bucket"], objs[0].key)
                .get()["Body"]
                .read()
            )
            self.assertEqual(blob["username"], expected_user_name)
            self.assertEqual(blob["request_path"], "/somepath")
            self.assertEqual(blob["ip"], "8.8.8.8")

            audit_data = blob["audit_data"]

            [self.assertEqual(data["model"], User.__name__) for data in audit_data]

            origin_data_pks = [data.pk for data in User.objects.all()]
            self.assertEqual(len(origin_data_pks), len(audit_data))
            [self.assertIn(data["primary_key"], origin_data_pks) for data in audit_data]
