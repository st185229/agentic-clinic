
import boto3, json, os

# Step 1: check credentials
sts = boto3.client("sts", region_name="us-east-1")
try:
    identity = sts.get_caller_identity()
    print(f"✓ AWS credentials OK — Account: {identity['Account']}")
except Exception as e:
    print(f"✗ AWS credentials FAILED: {e}")
    exit(1)

# Step 2: check Bedrock connectivity
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
try:
    resp = bedrock.invoke_model(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "Say hello."}]
        }),
        contentType="application/json",
        accept="application/json"
    )
    body = json.loads(resp["body"].read())
    print(f"✓ Bedrock OK — Response: {body['content'][0]['text']}")
except Exception as e:
    print(f"✗ Bedrock FAILED: {e}")
