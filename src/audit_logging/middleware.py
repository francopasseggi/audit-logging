import json
import boto3
import time

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Page
from django.db.models import Model
from django.db.models.query import QuerySet
from django.utils import timezone

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer

from audit_logging.utils import AuditableResponse

from typing import TypedDict


"""
Middleware to extract the primary key of any model object that is egressed by backend API
In order for the middleware to detect egressed data a serializer object needs to be present in the response object.
This happens automatically for any view declared as part of a builtin ViewSet object and returns a QuerySet or Page rather 
than a response. 
If the view is not declared as part of a built in ViewSet or returns a Response object and the function requires audit logs
then the return type needs to be switched to AuditableResponse
"""


class AuditDataElement(TypedDict):
    model: str
    primary_key: str


class AuditPayload(TypedDict):
    username: str
    request_path: str
    access_time: str
    ip: str
    elapsed_time_seconds: str
    audit_data: list[AuditDataElement]
    service_name: str | None


class EgressAuditLogMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response
        self.client = boto3.client("s3")
        self._configure_logging()

    def _configure_logging(self) -> None:
        self.logging_config = settings.EGRESS_LOGGING_CONFIGURATION

        match self.logging_config["log_type"]:
            case "s3":
                if "s3_bucket" not in self.logging_config.keys():
                    raise ImproperlyConfigured(
                        "S3 logging is selected for egress logging but no bucket is specified"
                    )

                self.s3_bucket = self.logging_config["s3_bucket"]
                self.log_func = self.log_s3

            case "std_out":
                self.log_func = self.log_std_out

            case _:
                raise ImproperlyConfigured(
                    f"Unknown logging type passed to egress logger {self.logging_config['log_type']}"
                )

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        end_time = time.time()

        try:
            if (
                isinstance(response, AuditableResponse)
                and response.auditable_content != None
            ):
                self._enrich_and_log_audit_data(
                    request, response.auditable_content, end_time - start_time
                )
            else:
                serializers = self._extract_serializers_from_response(response)
                audit_data = self._extract_egressed_data_ids_from_response(serializers)

                if len(audit_data) != 0:
                    log_payload = self._enrich_audit_data(
                        request, audit_data, end_time - start_time
                    )
                    self.log_func(log_payload)

        # log and swallow exception here, we dont want a logging error breaking a user request
        except Exception as e:
            print(f"Failed to upload audit logs for request with exception {e}")

        return response

    def _extract_serializers_from_response(
        self, response: Response
    ) -> list[Serializer]:
        serializers = []

        # case where the response is an AuditableResponse
        if isinstance(response, AuditableResponse) and response.serializers != None:
            serializers = response.serializers

        # case where response was generated by a built-in ViewSet
        elif hasattr(response, "data"):
            if hasattr(response.data, "serializer"):
                serializers.append(response.data.serializer)

            for member in response.data:
                if hasattr(response.data[member], "serializer"):
                    serializers.append(response.data[member].serializer)

                elif (
                    type(response.data[member]) == dict
                    and "serializer" in response.data[member].keys()
                ) and response.data[member]["serializer"] is not None:
                    serializers.append(response.data[member]["serializer"])

        # if we cant extract serializers from the request then we assume this is not a route that requires audit logging
        return serializers

    def _extract_egressed_data_ids_from_response(
        self, serializers: list[Serializer]
    ) -> list[AuditDataElement]:
        audit_data = []

        for serializer in serializers:
            egressed_data = None
            if isinstance(serializer.instance, QuerySet) or isinstance(
                serializer.instance, list
            ):
                egressed_data = serializer.instance

            elif isinstance(serializer.instance, Page):
                egressed_data = serializer.instance.object_list

            elif isinstance(serializer.instance, set):
                egressed_data = list(serializer.instance)

            elif isinstance(serializer.instance, Model):
                egressed_data = [serializer.instance]

            else:
                print(
                    f"Unknown serializer type {type(serializer.instance)} encountered by egress audit logger"
                )

            if egressed_data != None:
                for data_point in egressed_data:
                    audit_data.append(
                        AuditDataElement(
                            model=type(data_point).__name__, primary_key=data_point.pk
                        )
                    )

        return audit_data

    def _enrich_audit_data(
        self, request: Request, audit_data: list[AuditDataElement], elapsed_time: float
    ) -> AuditPayload:
        username = self._get_user_identifying_information(request=request)
        ip = self._get_caller_ip(request=request)
        timestamp = timezone.now().isoformat()
        request_path = request.path

        return AuditPayload(
            username=username,
            ip=ip,
            request_path=request_path,
            access_time=timestamp,
            elapsed_time_seconds=elapsed_time,
            audit_data=audit_data,
            service_name=settings.EGRESS_LOGGING_CONFIGURATION.get("service_name"),
        )

    def _get_user_identifying_information(self, request: Request) -> str:
        if request.user.is_authenticated:
            return request.user.username
        else:
            return "Anonymous"

    def _get_caller_ip(self, request: Request) -> str:
        if x_forwarded_for := request.META.get("HTTP_X_FORWARDED_FOR"):
            return x_forwarded_for.split(",")[0].strip()
        elif real_ip := request.META.get("HTTP_X_REAL_IP"):
            return real_ip
        else:
            return request.META.get("REMOTE_ADDR")

    # New logging mechanisms can be defined here. Configuration should be handled in _configure_logging()
    # The only allowed parameter is audit_data, which is required, and will be a AuditPayload instance.
    def log_s3(self, audit_data: AuditPayload) -> None:
        key = f"{uuid4()}.json"
        data_bytes = json.dumps(audit_data).encode("utf-8")
        self.client.put_object(Body=data_bytes, Bucket=self.s3_bucket, Key=key)

    def log_std_out(self, audit_data: AuditPayload) -> None:
        data_str = json.dumps(audit_data)
        print(data_str)
