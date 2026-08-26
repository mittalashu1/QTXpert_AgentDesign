# Admin AI Cost Reconciliation

QTXpert reports two distinct cost sources on the admin dashboard:

- **QTXpert metered estimate**: token usage recorded by QTXpert and priced using `LLM_COST_RATES_JSON`.
- **Azure actual cost**: billed Azure resource cost retrieved from Azure Cost Management.

The two values are intentionally not treated as interchangeable. Azure billing can include usage outside QTXpert, historical usage from before QTXpert metering was enabled, and billing adjustments.

## Azure Cost Management configuration

Set the following secrets on the backend service:

- `AZURE_COST_TENANT_ID`
- `AZURE_COST_CLIENT_ID`
- `AZURE_COST_CLIENT_SECRET`
- `AZURE_COST_SUBSCRIPTION_ID`
- `AZURE_COST_RESOURCE_GROUP`
- `AZURE_COST_RESOURCE_NAME` (optional when it can be derived from `AZURE_ENDPOINT`)

Grant the Entra application Cost Management Reader or equivalent read permission at the selected resource-group or subscription scope.

If these settings are absent, the dashboard displays **Not connected** instead of incorrectly presenting `$0` as the Azure bill. If Azure is connected but the API cannot be queried, the dashboard displays **Unavailable** together with a non-secret error message.

Azure billing data may lag real-time model usage. The dashboard therefore displays the last successful Azure sync time separately from QTXpert's internal metering.
