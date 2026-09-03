#!/usr/bin/env sh
# Render starts the backend through this script so AWS APM can be enabled
# without changing the application code or the default startup path.
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head || echo "WARNING: database migrations were deferred; continuing in degraded mode" >&2
fi

if [ "${AWS_APM_ENABLED:-false}" = "true" ]; then
  aws_region="${AWS_REGION:-us-east-1}"
  service_name="${AWS_APM_SERVICE_NAME:-qtxpert-backend}"
  environment_name="${AWS_APM_ENVIRONMENT:-production}"

  # ADOT's AWS configurator signs the OTLP requests with the credentials
  # discovered by the AWS SDK. Keep these defaults explicit and bounded.
  export OTEL_PYTHON_DISTRO="${OTEL_PYTHON_DISTRO:-aws_distro}"
  export OTEL_PYTHON_CONFIGURATOR="${OTEL_PYTHON_CONFIGURATOR:-aws_configurator}"
  # Application Signals metrics are intentionally disabled here. X-Ray traces
  # plus Render's native metrics cover the backend without double-ingesting
  # transaction-search data; enable a separate metrics pipeline if required.
  export OTEL_METRICS_EXPORTER="${OTEL_METRICS_EXPORTER:-none}"
  export OTEL_TRACES_EXPORTER="${OTEL_TRACES_EXPORTER:-otlp}"
  export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL="${OTEL_EXPORTER_OTLP_TRACES_PROTOCOL:-http/protobuf}"
  export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-https://xray.${aws_region}.amazonaws.com/v1/traces}"
  export OTEL_TRACES_SAMPLER="${OTEL_TRACES_SAMPLER:-parentbased_traceidratio}"
  export OTEL_TRACES_SAMPLER_ARG="${OTEL_TRACES_SAMPLER_ARG:-${AWS_APM_TRACE_SAMPLE_RATIO:-0.05}}"
  export OTEL_AWS_APPLICATION_SIGNALS_ENABLED="${OTEL_AWS_APPLICATION_SIGNALS_ENABLED:-false}"
  export OTEL_PYTHON_LOG_CORRELATION="${OTEL_PYTHON_LOG_CORRELATION:-true}"
  resource_attributes="service.name=${service_name},deployment.environment=${environment_name}"
  if [ -n "${AWS_APM_LOG_GROUP:-}" ]; then
    # Application Signals uses this attribute to correlate trace metrics with
    # the CloudWatch log group configured below.
    resource_attributes="${resource_attributes},aws.log.group.names=${AWS_APM_LOG_GROUP}"
  fi
  export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES:-${resource_attributes}}"

  # CloudWatch OTLP log streams must exist before ADOT starts exporting.
  # Without an explicit group/stream, keep log exporting off and continue
  # sending traces; this prevents a typo from making the app unavailable.
  if [ -n "${AWS_APM_LOG_GROUP:-}" ] && [ -n "${AWS_APM_LOG_STREAM:-}" ]; then
    export OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-otlp}"
    export OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED="${OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED:-true}"
    export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL="${OTEL_EXPORTER_OTLP_LOGS_PROTOCOL:-http/protobuf}"
    export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-https://logs.${aws_region}.amazonaws.com/v1/logs}"
    export OTEL_EXPORTER_OTLP_LOGS_HEADERS="${OTEL_EXPORTER_OTLP_LOGS_HEADERS:-x-aws-log-group=${AWS_APM_LOG_GROUP},x-aws-log-stream=${AWS_APM_LOG_STREAM}}"
  else
    export OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-none}"
  fi

  echo "AWS APM enabled service=${service_name} environment=${environment_name} region=${aws_region} trace_sample=${OTEL_TRACES_SAMPLER_ARG}"
  exec opentelemetry-instrument uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

