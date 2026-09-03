# AWS APM setup for QTXpert

QTXpert currently runs as a Docker web service on Render. Its normal logs are
available in Render, and AWS Bedrock credentials (when configured) are used
only by the Bedrock LLM provider. AWS Application Performance Monitoring is a
separate, opt-in telemetry path.

This repository includes the AWS Distro for OpenTelemetry (ADOT) Python
auto-instrumenter. When `AWS_APM_ENABLED=true`, it instruments the FastAPI
backend and sends traces to the AWS X-Ray OTLP endpoint. If a CloudWatch log
group and stream are configured, it also sends correlated logs to the
CloudWatch OTLP endpoint. The default trace sample ratio is 5% to avoid the
high ingestion cost of sampling every request.

## What is required from the AWS account

1. Choose the AWS region that should own the telemetry. Keep it the same as
   `AWS_REGION` used by the backend. AWS Application Signals service names and
   environments are explicit for non-AWS hosts such as Render.
2. Enable CloudWatch Application Signals in that account and enable X-Ray
   Transaction Search if trace search is required.
3. Create a log group and stream before enabling log export, for example:
   - log group: `/qtxpert/apm`
   - log stream: `render-backend`
4. Create a dedicated telemetry IAM principal. Prefer a role/temporary
   credential mechanism; if Render cannot assume the role in your setup, use a
   narrowly scoped access key stored only in Render's secret environment and
   rotate it.

The application-side write policy can be limited to X-Ray trace writes and the
pre-created CloudWatch log group:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "XRayTraceWrite",
      "Effect": "Allow",
      "Action": [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogGroupDiscovery",
      "Effect": "Allow",
      "Action": "logs:DescribeLogGroups",
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogStreamDiscovery",
      "Effect": "Allow",
      "Action": "logs:DescribeLogStreams",
      "Resource": "arn:aws:logs:<REGION>:<ACCOUNT_ID>:log-group:/qtxpert/apm"
    },
    {
      "Sid": "CloudWatchLogStreamWrite",
      "Effect": "Allow",
      "Action": "logs:PutLogEvents",
      "Resource": "arn:aws:logs:<REGION>:<ACCOUNT_ID>:log-group:/qtxpert/apm:log-stream:render-backend"
    }
  ]
}
```

If the telemetry principal must create streams, add `logs:CreateLogStream` for
the same log-group ARN. If you emit separate custom CloudWatch metrics, add a
separate `cloudwatch:PutMetricData` statement restricted by the appropriate
namespace; the default QTXpert path uses trace-derived Application Signals
metrics and does not add that permission.

For viewing dashboards, use a separate human/operator role with read-only
CloudWatch Application Signals, X-Ray, and CloudWatch Logs access. Do not give
the application write principal console or read access.

## Render configuration

Set these values on the backend service in Render's Environment page. Keep
credentials as secrets and never paste them into the repository or a chat:

```text
AWS_APM_ENABLED=true
AWS_REGION=<chosen-region>
AWS_APM_SERVICE_NAME=qtxpert-backend
AWS_APM_ENVIRONMENT=production
AWS_APM_TRACE_SAMPLE_RATIO=0.05
AWS_APM_LOG_GROUP=/qtxpert/apm
AWS_APM_LOG_STREAM=render-backend
```

The ADOT AWS configurator uses the standard AWS SDK credential chain. For the
Render fallback, set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as Render
secrets for the dedicated telemetry principal (and `AWS_SESSION_TOKEN` when
using temporary credentials). The same process may also call Bedrock, so use a
combined least-privilege role or move telemetry to a collector if Bedrock and
APM credentials must be isolated completely.

## Validation

After saving the environment values, redeploy the backend and verify:

1. Render startup contains `AWS APM enabled service=qtxpert-backend ...`.
2. The `/api/v1/health/live` probe remains 200.
3. Generate a small set of requests, then confirm traces in X-Ray/Application
   Signals and correlated logs in `/qtxpert/apm`.
4. If export is rejected, inspect Render logs for the AWS status and first
   correct the IAM/region/log-stream configuration. The app remains available;
   telemetry export is asynchronous and must not be allowed to block requests.

The deployment keeps APM disabled until these account-side prerequisites are
complete, so enabling the code path alone does not send data or incur AWS
telemetry charges.

