# AgentCore Runtime setup

## 1. Inbound auth (Cognito)

```bash
export REGION=us-east-1 USERNAME=macro-desk PASSWORD='<at least 8 chars>'

export POOL_ID=$(aws cognito-idp create-user-pool --pool-name MacroDeskPool \
  --policies '{"PasswordPolicy":{"MinimumLength":8}}' --region $REGION | jq -r '.UserPool.Id')

export CLIENT_ID=$(aws cognito-idp create-user-pool-client --user-pool-id $POOL_ID \
  --client-name MacroDeskClient --no-generate-secret \
  --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  --region $REGION | jq -r '.UserPoolClient.ClientId')

aws cognito-idp admin-create-user --user-pool-id $POOL_ID --username $USERNAME \
  --message-action SUPPRESS --region $REGION > /dev/null
aws cognito-idp admin-set-user-password --user-pool-id $POOL_ID --username $USERNAME \
  --password "$PASSWORD" --permanent --region $REGION

export BEARER_TOKEN=$(aws cognito-idp initiate-auth --client-id $CLIENT_ID \
  --auth-flow USER_PASSWORD_AUTH --auth-parameters USERNAME=$USERNAME,PASSWORD="$PASSWORD" \
  --region $REGION | jq -r '.AuthenticationResult.AccessToken')
```

## 2. Deploy

Follow the commands in the top-level README. `main.py` in this folder is the runtime entrypoint.

## 3. Smoke test

```bash
export AGENT_ARN=<arn printed by agentcore deploy>
ENC=$(printf %s "$AGENT_ARN" | jq -sRr @uri)
URL="https://bedrock-agentcore.$REGION.amazonaws.com/runtimes/$ENC/invocations?qualifier=DEFAULT"

curl -sS "$URL" -H "Authorization: Bearer $BEARER_TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

curl -sS "$URL" -H "Authorization: Bearer $BEARER_TOKEN" -H 'MCP-Protocol-Version: 2025-11-25' \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"macro_briefing","arguments":{}}}'
```

FRED is fetched over the public internet, so the runtime needs outbound network access (the default public network mode).
