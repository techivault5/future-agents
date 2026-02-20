# Claude API on AWS Lambda — Complete Guide

A complete guide to building a Claude-powered REST API and deploying it to AWS Lambda with API Gateway.

---

## Architecture Overview

```
Client (HTTP Request)
        │
        ▼
  API Gateway (REST)
        │
        ▼
  AWS Lambda (Python)
        │
        ▼
  Claude API (claude-opus-4-6)
        │
        ▼
  API Gateway Response
        │
        ▼
Client (HTTP Response)
```

**Components:**
- **AWS Lambda** — Serverless compute that runs the Claude API handler
- **Amazon API Gateway** — Exposes Lambda as a public HTTPS endpoint
- **AWS Secrets Manager** — Securely stores the Anthropic API key
- **IAM Role** — Grants Lambda permission to access Secrets Manager

---

## Prerequisites

- AWS account with permissions to create Lambda, API Gateway, IAM, and Secrets Manager resources
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) installed and configured (`aws configure`)
- Python 3.11+
- `pip` and `zip` available on your machine
- Anthropic API key (get one at [console.anthropic.com](https://console.anthropic.com))

---

## Project Structure

```
claude-lambda-api/
├── lambda/
│   ├── handler.py          # Main Lambda handler
│   ├── requirements.txt    # Python dependencies
│   └── utils.py            # Shared utilities
├── deploy.sh               # Deployment script
└── test_api.sh             # API test script
```

---

## Step 1 — Store API Key in AWS Secrets Manager

Never hardcode secrets. Store your Anthropic API key securely:

```bash
aws secretsmanager create-secret \
  --name "anthropic/api-key" \
  --description "Anthropic API key for Claude" \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-YOUR-KEY-HERE"}'
```

Note the **ARN** returned — you will need it for the IAM policy.

---

## Step 2 — Create IAM Role for Lambda

### 2a. Trust Policy (`trust-policy.json`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### 2b. Create the Role

```bash
aws iam create-role \
  --role-name claude-lambda-role \
  --assume-role-policy-document file://trust-policy.json
```

### 2c. Attach Basic Lambda Execution Policy

```bash
aws iam attach-role-policy \
  --role-name claude-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 2d. Secrets Manager Access Policy (`secrets-policy.json`)

Replace `YOUR-SECRET-ARN` with the ARN from Step 1:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:YOUR-ACCOUNT-ID:secret:anthropic/api-key*"
    }
  ]
}
```

```bash
aws iam put-role-policy \
  --role-name claude-lambda-role \
  --policy-name secrets-access \
  --policy-document file://secrets-policy.json
```

---

## Step 3 — Lambda Function Code

### `lambda/requirements.txt`

```
anthropic==0.40.0
```

### `lambda/utils.py`

```python
import json
import boto3
from functools import lru_cache

SECRET_NAME = "anthropic/api-key"
REGION = "us-east-1"


@lru_cache(maxsize=1)
def get_api_key() -> str:
    """Fetch the Anthropic API key from Secrets Manager (cached per container)."""
    client = boto3.client("secretsmanager", region_name=REGION)
    response = client.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(response["SecretString"])
    return secret["ANTHROPIC_API_KEY"]


def api_response(status_code: int, body: dict) -> dict:
    """Build a standard API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def parse_body(event: dict) -> dict:
    """Safely parse the request body from the API Gateway event."""
    body = event.get("body", "{}")
    if isinstance(body, str):
        return json.loads(body)
    return body or {}
```

### `lambda/handler.py`

```python
import anthropic
from utils import get_api_key, api_response, parse_body

# Supported routes
ROUTES = {
    "POST /chat": "handle_chat",
    "POST /chat/stream": "handle_chat_stream",
    "POST /summarize": "handle_summarize",
    "POST /extract": "handle_extract",
}


def lambda_handler(event: dict, context) -> dict:
    """
    Main Lambda entry point. Routes requests based on HTTP method + path.

    Supported endpoints:
      POST /chat          — Multi-turn chat with Claude
      POST /chat/stream   — Streaming chat (returns full response, streamed internally)
      POST /summarize     — Summarize provided text
      POST /extract       — Extract structured data from text
    """
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    route_key = f"{method} {path}"

    # Handle CORS preflight
    if method == "OPTIONS":
        return api_response(200, {"message": "OK"})

    handler_name = ROUTES.get(route_key)
    if not handler_name:
        return api_response(404, {"error": f"Route not found: {route_key}"})

    try:
        handler_fn = globals()[handler_name]
        return handler_fn(event)
    except anthropic.AuthenticationError:
        return api_response(401, {"error": "Invalid Anthropic API key."})
    except anthropic.RateLimitError:
        return api_response(429, {"error": "Rate limit exceeded. Please retry later."})
    except anthropic.BadRequestError as e:
        return api_response(400, {"error": f"Bad request: {str(e)}"})
    except ValueError as e:
        return api_response(400, {"error": str(e)})
    except Exception as e:
        print(f"Unhandled error: {e}")
        return api_response(500, {"error": "Internal server error."})


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------

def handle_chat(event: dict) -> dict:
    """
    POST /chat

    Request body:
      {
        "messages": [{"role": "user", "content": "Hello!"}],
        "system": "You are a helpful assistant.",   // optional
        "max_tokens": 1024                           // optional, default 1024
      }

    Response:
      {
        "response": "Hello! How can I help you?",
        "usage": {"input_tokens": 12, "output_tokens": 9}
      }
    """
    body = parse_body(event)

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise ValueError("'messages' must be a non-empty list.")

    system_prompt = body.get("system", "You are a helpful assistant.")
    max_tokens = int(body.get("max_tokens", 1024))

    client = anthropic.Anthropic(api_key=get_api_key())

    # Use streaming internally with get_final_message() to avoid Lambda timeouts
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        thinking={"type": "adaptive"},
        messages=messages,
    ) as stream:
        message = stream.get_final_message()

    # Extract the text response (skip thinking blocks)
    text_blocks = [b.text for b in message.content if b.type == "text"]
    response_text = "\n".join(text_blocks)

    return api_response(200, {
        "response": response_text,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    })


def handle_chat_stream(event: dict) -> dict:
    """
    POST /chat/stream

    Same request format as /chat. Returns the full streamed response.
    (Lambda does not support true HTTP streaming; this uses internal streaming
    to avoid timeouts on long responses, then returns the complete message.)

    Request body:
      {
        "messages": [{"role": "user", "content": "Write a long essay..."}],
        "system": "...",      // optional
        "max_tokens": 4096    // optional, default 4096
      }
    """
    body = parse_body(event)

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise ValueError("'messages' must be a non-empty list.")

    system_prompt = body.get("system", "You are a helpful assistant.")
    max_tokens = int(body.get("max_tokens", 4096))

    client = anthropic.Anthropic(api_key=get_api_key())

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        thinking={"type": "adaptive"},
        messages=messages,
    ) as stream:
        message = stream.get_final_message()

    text_blocks = [b.text for b in message.content if b.type == "text"]
    response_text = "\n".join(text_blocks)

    return api_response(200, {
        "response": response_text,
        "model": message.model,
        "stop_reason": message.stop_reason,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    })


def handle_summarize(event: dict) -> dict:
    """
    POST /summarize

    Request body:
      {
        "text": "Long text to summarize...",
        "style": "bullet"   // optional: "bullet" | "paragraph" | "short" (default: "paragraph")
      }

    Response:
      {
        "summary": "...",
        "usage": {...}
      }
    """
    body = parse_body(event)

    text = body.get("text", "").strip()
    if not text:
        raise ValueError("'text' field is required and cannot be empty.")

    style = body.get("style", "paragraph")
    style_instructions = {
        "bullet": "Summarize as concise bullet points.",
        "paragraph": "Summarize as a clear, concise paragraph.",
        "short": "Summarize in one or two sentences maximum.",
    }.get(style, "Summarize as a clear, concise paragraph.")

    client = anthropic.Anthropic(api_key=get_api_key())

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=f"You are a summarization assistant. {style_instructions}",
        messages=[{"role": "user", "content": f"Summarize the following:\n\n{text}"}],
    ) as stream:
        message = stream.get_final_message()

    summary = next((b.text for b in message.content if b.type == "text"), "")

    return api_response(200, {
        "summary": summary,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    })


def handle_extract(event: dict) -> dict:
    """
    POST /extract

    Extract structured data from text using Claude's structured output.

    Request body:
      {
        "text": "John Smith, john@example.com, Senior Engineer at Acme Corp.",
        "fields": ["name", "email", "job_title", "company"]
      }

    Response:
      {
        "extracted": {"name": "John Smith", "email": "john@example.com", ...},
        "usage": {...}
      }
    """
    body = parse_body(event)

    text = body.get("text", "").strip()
    if not text:
        raise ValueError("'text' field is required and cannot be empty.")

    fields = body.get("fields", [])
    if not fields or not isinstance(fields, list):
        raise ValueError("'fields' must be a non-empty list of field names to extract.")

    fields_str = ", ".join(fields)
    system_prompt = (
        "You are a data extraction assistant. Extract the requested fields from the text. "
        "Return ONLY a valid JSON object with the requested fields as keys. "
        "Use null for missing fields."
    )
    user_message = (
        f"Extract these fields: {fields_str}\n\n"
        f"From this text:\n{text}\n\n"
        f"Return only a JSON object."
    )

    client = anthropic.Anthropic(api_key=get_api_key())

    import json as _json

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        output_config={
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {field: {"type": ["string", "null"]} for field in fields},
                    "required": fields,
                    "additionalProperties": False,
                },
            }
        },
        messages=[{"role": "user", "content": user_message}],
    )

    raw = next((b.text for b in response.content if b.type == "text"), "{}")
    extracted = _json.loads(raw)

    return api_response(200, {
        "extracted": extracted,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    })
```

---

## Step 4 — Build the Deployment Package

Create a script to package the Lambda function with its dependencies:

### `deploy.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

FUNCTION_NAME="claude-api"
REGION="us-east-1"
ROLE_ARN="arn:aws:iam::YOUR-ACCOUNT-ID:role/claude-lambda-role"
RUNTIME="python3.11"
TIMEOUT=30        # seconds (max 900)
MEMORY=256        # MB

echo "==> Building deployment package..."
rm -rf build/ package.zip

# Install dependencies into build/
pip install -r lambda/requirements.txt --target build/ --quiet

# Copy Lambda source files
cp lambda/handler.py build/
cp lambda/utils.py build/

# Create zip archive
cd build && zip -r ../package.zip . -q && cd ..

PACKAGE_SIZE=$(du -sh package.zip | cut -f1)
echo "    Package size: $PACKAGE_SIZE"

# Check if function already exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
    >/dev/null 2>&1; then
  echo "==> Updating existing Lambda function..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://package.zip \
    --region "$REGION" \
    --output text --query 'FunctionArn'
else
  echo "==> Creating new Lambda function..."
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime "$RUNTIME" \
    --role "$ROLE_ARN" \
    --handler handler.lambda_handler \
    --zip-file fileb://package.zip \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY" \
    --environment "Variables={SECRET_NAME=anthropic/api-key,AWS_DEFAULT_REGION=$REGION}" \
    --region "$REGION" \
    --output text --query 'FunctionArn'
fi

echo "==> Waiting for update to complete..."
aws lambda wait function-updated \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION"

echo "Done! Lambda function '$FUNCTION_NAME' is ready."
```

```bash
chmod +x deploy.sh
./deploy.sh
```

---

## Step 5 — Create API Gateway

### 5a. Create the REST API

```bash
# Create the API
API_ID=$(aws apigateway create-rest-api \
  --name "claude-api" \
  --description "Claude-powered REST API" \
  --region us-east-1 \
  --query 'id' --output text)

echo "API ID: $API_ID"

# Get the root resource ID
ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id "$API_ID" \
  --region us-east-1 \
  --query 'items[?path==`/`].id' --output text)
```

### 5b. Create Resources and Methods

Repeat for each endpoint (`/chat`, `/chat/stream`, `/summarize`, `/extract`).
Example shown for `/chat`:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
LAMBDA_ARN="arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:claude-api"

# Create /chat resource
CHAT_ID=$(aws apigateway create-resource \
  --rest-api-id "$API_ID" \
  --parent-id "$ROOT_ID" \
  --path-part "chat" \
  --region us-east-1 \
  --query 'id' --output text)

# Add POST method (no auth for demo; add API key auth for production)
aws apigateway put-method \
  --rest-api-id "$API_ID" \
  --resource-id "$CHAT_ID" \
  --http-method POST \
  --authorization-type NONE \
  --region us-east-1

# Connect to Lambda
aws apigateway put-integration \
  --rest-api-id "$API_ID" \
  --resource-id "$CHAT_ID" \
  --http-method POST \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations" \
  --region us-east-1

# Grant API Gateway permission to invoke Lambda
aws lambda add-permission \
  --function-name claude-api \
  --statement-id apigateway-chat-post \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:us-east-1:${ACCOUNT_ID}:${API_ID}/*/POST/chat" \
  --region us-east-1
```

> Repeat the above block for `/chat/stream`, `/summarize`, and `/extract`, changing resource names and statement IDs accordingly.

### 5c. Deploy the API

```bash
aws apigateway create-deployment \
  --rest-api-id "$API_ID" \
  --stage-name prod \
  --region us-east-1

echo "API URL: https://${API_ID}.execute-api.us-east-1.amazonaws.com/prod"
```

---

## Step 6 — Test the API

### `test_api.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/prod"

echo "=== Test 1: POST /chat ==="
curl -s -X POST "$BASE_URL/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is 2 + 2? Answer briefly."}],
    "system": "You are a concise math assistant."
  }' | python3 -m json.tool

echo ""
echo "=== Test 2: POST /summarize ==="
curl -s -X POST "$BASE_URL/summarize" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "AWS Lambda is a serverless compute service that lets you run code without provisioning or managing servers. You pay only for the compute time you consume — there is no charge when your code is not running.",
    "style": "bullet"
  }' | python3 -m json.tool

echo ""
echo "=== Test 3: POST /extract ==="
curl -s -X POST "$BASE_URL/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Contact Jane Doe at jane.doe@acmecorp.com. She is a Senior Software Engineer at Acme Corp.",
    "fields": ["name", "email", "job_title", "company"]
  }' | python3 -m json.tool
```

```bash
chmod +x test_api.sh
./test_api.sh
```

---

## Step 7 — Add API Key Authentication (Production)

Protect your endpoint with an API key:

```bash
# Create usage plan and API key
KEY_ID=$(aws apigateway create-api-key \
  --name "claude-api-key" \
  --enabled \
  --region us-east-1 \
  --query 'id' --output text)

PLAN_ID=$(aws apigateway create-usage-plan \
  --name "claude-api-plan" \
  --api-stages "apiId=${API_ID},stage=prod" \
  --throttle "burstLimit=100,rateLimit=50" \
  --quota "limit=10000,period=MONTH" \
  --region us-east-1 \
  --query 'id' --output text)

aws apigateway create-usage-plan-key \
  --usage-plan-id "$PLAN_ID" \
  --key-id "$KEY_ID" \
  --key-type API_KEY \
  --region us-east-1

# Get the actual key value
aws apigateway get-api-key \
  --api-key "$KEY_ID" \
  --include-value \
  --region us-east-1 \
  --query 'value' --output text
```

Then update your methods to require an API key:

```bash
aws apigateway update-method \
  --rest-api-id "$API_ID" \
  --resource-id "$CHAT_ID" \
  --http-method POST \
  --patch-operations op=replace,path=/apiKeyRequired,value=true \
  --region us-east-1
```

Call the API with the key:

```bash
curl -X POST "$BASE_URL/chat" \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR-API-KEY" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

---

## Step 8 — Monitor with CloudWatch

Lambda automatically sends logs to CloudWatch. View them:

```bash
# Tail logs in real time
aws logs tail "/aws/lambda/claude-api" --follow --region us-east-1

# Get recent error logs
aws logs filter-log-events \
  --log-group-name "/aws/lambda/claude-api" \
  --filter-pattern "ERROR" \
  --region us-east-1
```

---

## Environment Variables Reference

| Variable | Description | Example |
|---|---|---|
| `SECRET_NAME` | Secrets Manager secret name | `anthropic/api-key` |
| `AWS_DEFAULT_REGION` | AWS region | `us-east-1` |

---

## Cost Estimate

| Service | Free Tier | Paid |
|---|---|---|
| Lambda | 1M requests/month | $0.20 per 1M requests |
| Lambda compute | 400K GB-seconds/month | $0.0000166667 per GB-second |
| API Gateway | 1M REST calls/month | $3.50 per 1M calls |
| Secrets Manager | 30-day trial | $0.40/secret/month |
| Claude API (Opus 4.6) | — | $5.00/1M input tokens, $25.00/1M output tokens |

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| `401 Unauthorized` | Wrong API key in Secrets Manager | Re-run Step 1 with correct key |
| `Task timed out` | Response too slow | Increase Lambda timeout in deploy.sh |
| `AccessDeniedException` | Missing IAM permissions | Verify the Secrets Manager policy in Step 2 |
| `502 Bad Gateway` | Lambda threw an uncaught exception | Check CloudWatch logs |
| `429 Too Many Requests` | Claude rate limit hit | Add retry logic or switch to Haiku model |
| Package too large (>250MB) | Too many dependencies | Use Lambda layers for `anthropic` package |

---

## Using Lambda Layers (Optional — for large packages)

If your deployment package exceeds 50 MB (unzipped 250 MB), move dependencies to a Lambda layer:

```bash
# Build the layer
mkdir -p layer/python
pip install anthropic --target layer/python --quiet
cd layer && zip -r ../anthropic-layer.zip . -q && cd ..

# Publish the layer
LAYER_ARN=$(aws lambda publish-layer-version \
  --layer-name anthropic-sdk \
  --zip-file fileb://anthropic-layer.zip \
  --compatible-runtimes python3.11 \
  --region us-east-1 \
  --query 'LayerVersionArn' --output text)

echo "Layer ARN: $LAYER_ARN"

# Attach layer to function
aws lambda update-function-configuration \
  --function-name claude-api \
  --layers "$LAYER_ARN" \
  --region us-east-1
```

Then remove `anthropic` from `requirements.txt` and rebuild only your source files.

---

## Quick Reference — Full Deploy Commands

```bash
# 1. Store API key
aws secretsmanager create-secret \
  --name "anthropic/api-key" \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-YOUR-KEY"}'

# 2. Create IAM role
aws iam create-role --role-name claude-lambda-role \
  --assume-role-policy-document file://trust-policy.json
aws iam attach-role-policy --role-name claude-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name claude-lambda-role \
  --policy-name secrets-access \
  --policy-document file://secrets-policy.json

# 3. Build and deploy Lambda
./deploy.sh

# 4. Create API Gateway, resources, and deploy stage (see Step 5)

# 5. Test
./test_api.sh
```

---

## Summary

You now have a production-ready Claude API on AWS Lambda with:

- **4 REST endpoints**: `/chat`, `/chat/stream`, `/summarize`, `/extract`
- **Secure API key storage** via Secrets Manager
- **Streaming internally** to avoid Lambda timeouts on long responses
- **Structured outputs** for the `/extract` endpoint
- **CORS headers** for browser clients
- **CloudWatch logging** for observability
- **API key authentication** for access control
