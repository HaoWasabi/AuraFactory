import boto3  

# Khởi tạo client
client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Gọi model Amazon Nova Lite
response = client.converse_stream( 
    modelId="amazon.nova-lite-v1:0", 
    messages=[
        { 
            "role": "user", 
            "content": [{"text": "Tell me a short story about a robot."}]
        }
    ]
)

# Xử lý stream (Logic này vẫn đúng với Nova Lite)
for event in response["stream"]: 
    if "contentBlockDelta" in event: 
        delta = event["contentBlockDelta"]["delta"] 
        if "text" in delta: 
            print(delta["text"], end="", flush=True)