# Django Egress Audit Logging Middleware

## Overview

This Django package provides middleware for audit logging of egressed data from Django REST Framework (DRF) endpoints. It supports logging to an AWS S3 bucket or standard output. The middleware captures and logs key details about each request, including the user, request path, IP address, response time, and primary keys of egressed model instances.

## Features

- Automatic detection and logging of egressed model instance data
- Support for AWS S3 and standard output logging
- Easy integration with Django REST Framework
- Custom `AuditableResponse` class to facilitate logging

## Installation

<!-- TODO: Modify this: include a command to install with poetry -->

1. Clone this repository or download the package.
2. Install the package into your Django project. Ensure you have `boto3` and `django-rest-framework` installed, as they are dependencies.

## Configuration

<!-- TODO: Add variable prefix to the logs, with variable configured in project settings -->

1. Add the middleware to your Django settings:

   ```python
   MIDDLEWARE = [
       ...
       'audit_logging.middleware.EgressAuditLogMiddleware',
       ...
   ]
   ```

2. Configure the logging settings in your Django settings:

   ```python
   EGRESS_LOGGING_CONFIGURATION = {
       "service_name": "<your-service-name>" # Used for identifying the logs service
       "log_type": "s3",  # Options: "s3", "std_out"
       "s3_bucket": "<your-s3-bucket-name>",  # Required if log_type is "s3"
   }
   ```

## Usage

1. Use the `AuditableResponse` class in your views when you want to ensure logging of egressed data:

   ```python
   from audit_logging.utils import AuditableResponse

   def my_view(request):
       ...
       return AuditableResponse(data=my_data, auditable_serializers=[my_serializer])
   ```

2. The middleware will automatically handle logging for views that return `QuerySet`, `Page`, or standard DRF responses when applicable.

## Testing

The package includes test cases under `tests.py`. Use Django's test framework to run these tests.
