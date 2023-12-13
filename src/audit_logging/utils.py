from rest_framework.response import Response
from rest_framework.serializers import Serializer

from typing import Any, Optional


class AuditableResponse(Response):
    def __init__(
        self,
        data: Any = None,
        status: Optional[int] = None,
        template_name: Optional[str] = None,
        headers: Optional[dict[str, any]] = None,
        exception: bool = False,
        content_type: Optional[str] = None,
        auditable_serializers: list[Serializer] = None,
        auditable_content: list = None,
    ):
        super().__init__(
            data=data,
            status=status,
            template_name=template_name,
            headers=headers,
            exception=exception,
            content_type=content_type,
        )
        self.serializers = auditable_serializers
        self.auditable_content = auditable_content
