from strands_agent import agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def standup_agent(payload):
    response = agent(payload.get("prompt", "Write my standup for today"))
    return response.message["content"][0]["text"]


if __name__ == "__main__":
    app.run()
