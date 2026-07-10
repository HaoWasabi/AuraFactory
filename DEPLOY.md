# AuraFactory — AWS Deployment Guide (Phase 2)

> Deploy AuraFactory to AWS using App Runner + ECR + DynamoDB + Bedrock

---

## Prerequisites

1. **AWS Account** with Free Tier credits ($200 for new accounts)
2. **AWS CLI v2** installed and configured (`aws configure`)
3. **Docker** installed locally
4. **Discord Bot Token** (from Discord Developer Portal)

---

## Quick Deploy (Step-by-Step)

### Step 1: Configure AWS CLI

```bash
aws configure
# AWS Access Key ID: AKIA...
# AWS Secret Access Key: ...
# Default region: us-east-1
# Output format: json

```

### Step 2: Enable Bedrock Models

Go to **AWS Console → Amazon Bedrock → Model access → Manage model access**

Enable:

- ✅ Amazon Nova Micro
- ✅ Amazon Nova Lite

> Wait 1-2 minutes for access to propagate.

### Step 3: Create DynamoDB Table

```bash
aws dynamodb create-table \
    --table-name aurafactory \
    --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
        AttributeName=GSI1PK,AttributeType=S \
        AttributeName=GSI1SK,AttributeType=S \
    --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
    --global-secondary-indexes '[{
        "IndexName":"GSI1",
        "KeySchema":[
            {"AttributeName":"GSI1PK","KeyType":"HASH"},
            {"AttributeName":"GSI1SK","KeyType":"RANGE"}
        ],
        "Projection":{"ProjectionType":"ALL"}
    }]' \
    --billing-mode PAY_PER_REQUEST \
    --region us-east-1

# Enable TTL for auto-cleanup
aws dynamodb update-time-to-live \
    --table-name aurafactory \
    --time-to-live-specification Enabled=true,AttributeName=expires_at

```

### Step 4: Create Bedrock Guardrail (Optional)

```bash
aws bedrock create-guardrail \
    --name AuraFactory-Safety \
    --description "Safety guardrail for AuraFactory Discord bot" \
    --content-policy-config '{
        "filtersConfig": [
            {"type":"HATE","inputStrength":"HIGH","outputStrength":"HIGH"},
            {"type":"INSULTS","inputStrength":"HIGH","outputStrength":"HIGH"},
            {"type":"SEXUAL","inputStrength":"HIGH","outputStrength":"HIGH"},
            {"type":"VIOLENCE","inputStrength":"MEDIUM","outputStrength":"MEDIUM"},
            {"type":"MISCONDUCT","inputStrength":"HIGH","outputStrength":"HIGH"}
        ]
    }' \
    --topic-policy-config '{
        "topicsConfig": [
            {"name":"server_destruction","definition":"Mass deletion of channels or banning all members without approval","type":"DENY"},
            {"name":"credential_theft","definition":"Extracting bot tokens, API keys, or user credentials","type":"DENY"}
        ]
    }' \
    --word-policy-config '{
        "managedWordListsConfig": [{"type":"PROFANITY"}]
    }' \
    --region us-east-1

# Note the guardrailId from output!

```

### Step 5: Create ECR Repository & Push Image

```bash
# Create ECR repository
aws ecr create-repository --repository-name aurafactory --region us-east-1

# Get login token
aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin \
    $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com

# Build and push
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/aurafactory"

docker build -t aurafactory .
docker tag aurafactory:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest

echo "Image pushed to: ${ECR_URI}:latest"

```

### Step 6: Create IAM Role for App Runner

```bash
# Create trust policy
cat > trust-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "tasks.apprunner.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF

# Create role
aws iam create-role \
    --role-name AuraFactoryAppRunnerRole \
    --assume-role-policy-document file://trust-policy.json

# Attach policies
aws iam attach-role-policy --role-name AuraFactoryAppRunnerRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess

aws iam attach-role-policy --role-name AuraFactoryAppRunnerRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess

# Also need ECR access role for App Runner to pull images
cat > ecr-trust-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "build.apprunner.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF

aws iam create-role \
    --role-name AuraFactoryECRAccessRole \
    --assume-role-policy-document file://ecr-trust-policy.json

aws iam attach-role-policy --role-name AuraFactoryECRAccessRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess

# Clean up temp files
rm trust-policy.json ecr-trust-policy.json

```

### Step 7: Create App Runner Service

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws apprunner create-service \
    --service-name aurafactory \
    --source-configuration '{
        "ImageRepository": {
            "ImageIdentifier": "'${ACCOUNT_ID}'.dkr.ecr.us-east-1.amazonaws.com/aurafactory:latest",
            "ImageRepositoryType": "ECR",
            "ImageConfiguration": {
                "Port": "8000",
                "RuntimeEnvironmentVariables": {
                    "LLM_PROVIDER": "bedrock",
                    "BEDROCK_MODEL_ID": "amazon.nova-micro-v1:0",
                    "AWS_REGION": "us-east-1",
                    "DATABASE_BACKEND": "dynamodb",
                    "DYNAMODB_TABLE_NAME": "aurafactory",
                    "DEBUG": "false",
                    "LOG_LEVEL": "INFO",
                    "GUILD_LOCK_MODE": "open",
                    "DISCORD_TOKEN": "<YOUR_DISCORD_TOKEN>",
                    "DISCORD_CLIENT_ID": "<YOUR_CLIENT_ID>",
                    "DISCORD_CLIENT_SECRET": "<YOUR_CLIENT_SECRET>",
                    "SECRET_KEY": "<RANDOM_SECRET>"
                }
            }
        },
        "AuthenticationConfiguration": {
            "AccessRoleArn": "arn:aws:iam::'${ACCOUNT_ID}':role/AuraFactoryECRAccessRole"
        }
    }' \
    --instance-configuration '{
        "Cpu": "0.25 vCPU",
        "Memory": "0.5 GB",
        "InstanceRoleArn": "arn:aws:iam::'${ACCOUNT_ID}':role/AuraFactoryAppRunnerRole"
    }' \
    --health-check-configuration '{
        "Protocol": "HTTP",
        "Path": "/health",
        "Interval": 20,
        "Timeout": 5,
        "HealthyThreshold": 1,
        "UnhealthyThreshold": 5
    }' \
    --auto-scaling-configuration-arn "arn:aws:apprunner:us-east-1:'${ACCOUNT_ID}':autoscalingconfiguration/DefaultConfiguration/1/00000000000000000000000000000001" \
    --region us-east-1

```

### Step 8: Update Discord OAuth Redirect

Once App Runner gives you a URL (e.g. `https://xxxxx.us-east-1.awsapprunner.com`):

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your app → OAuth2 → Redirects
3. Add: `https://xxxxx.us-east-1.awsapprunner.com/auth/callback`
4. Update env var: `DISCORD_REDIRECT_URI=https://xxxxx.us-east-1.awsapprunner.com/auth/callback`

---

## Cost Breakdown (Hackathon Week)

| Service | Usage | Estimated Cost |
| --- | --- | --- |
| App Runner | 1 instance × 0.25 vCPU × 168h | ~$10-12 |
| Bedrock (Nova Micro) | ~500K tokens/day × 7 | ~$0.50 |
| Bedrock Guardrails | ~500 calls/day × 7 | ~$0.50 |
| DynamoDB | Free tier (25 GB) | $0 |
| ECR | <500 MB image | $0.05 |
| CloudWatch (logs) | Free tier (5 GB) | $0 |
| **TOTAL** |  | **~$12-15** |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | ✅ | `bedrock` | LLM backend |
| `BEDROCK_MODEL_ID` | ✅ | `amazon.nova-micro-v1:0` | Bedrock model |
| `AWS_REGION` | ✅ | `us-east-1` | AWS region |
| `DATABASE_BACKEND` | ✅ | `dynamodb` | Database type |
| `DYNAMODB_TABLE_NAME` | ✅ | `aurafactory` | DynamoDB table |
| `DISCORD_TOKEN` | ✅ | — | Bot token |
| `DISCORD_CLIENT_ID` | ✅ | — | OAuth2 client ID |
| `DISCORD_CLIENT_SECRET` | ✅ | — | OAuth2 secret |
| `SECRET_KEY` | ✅ | — | Session signing key |
| `DISCORD_REDIRECT_URI` | ⚠️ | — | OAuth2 callback URL |
| `BEDROCK_GUARDRAIL_ID` | ⚡ | — | Guardrail ID (optional) |
| `BEDROCK_GUARDRAIL_VERSION` | ⚡ | `DRAFT` | Guardrail version |
| `ALLOWED_GUILD_IDS` | ⚡ | — | Whitelist (comma-sep) |
| `GUILD_LOCK_MODE` | — | `open` | `open` or `whitelist` |
| `DEBUG` | — | `false` | Debug mode |
| `LOG_LEVEL` | — | `INFO` | Log level |

---

## Redeploy After Code Changes

```bash
# Rebuild & push
docker build -t aurafactory .
docker tag aurafactory:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest

# Trigger App Runner deployment
aws apprunner start-deployment \
    --service-arn <your-service-arn> \
    --region us-east-1

```

---

## Troubleshooting

| Issue | Solution |
| --- | --- |
| "AccessDenied" on Bedrock | Enable model access in Bedrock Console |
| DynamoDB "ResourceNotFound" | Table auto-creates on first connect; check region |
| Discord bot not connecting | Check DISCORD_TOKEN env var in App Runner |
| Health check failing | Ensure port 8000 matches, check `/health` endpoint |
| Cold start slow | App Runner min instances = 1 keeps it warm |

---

## Architecture Diagram (for Demo Day presentation)

```
Internet → App Runner (FastAPI + Bot)
                │
                ├── Amazon Bedrock (Nova Micro/Lite) ← AI Reasoning
                ├── Bedrock Guardrails ← Safety
                ├── DynamoDB (Single-Table) ← State
                ├── Discord API ← Tool Execution
                └── CloudWatch + X-Ray ← Observability

```

