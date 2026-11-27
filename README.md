# Slack Academic Policy Bot

Send one PDF notice and a question in a Slack DM. The bot reads the notice, lets Amazon Bedrock decide whether it needs a policy lookup, and runs that lookup over MCP. It replies in the thread with citations to the PDF pages or policy IDs it used.

The demo uses three fictional policies and a sample registration notice. The policy search requires topic and intent phrases. For example, Embedded Systems Lab and a prerequisite phrase are both required to return `LAB-101`. The reference data lives in [policy_bot/policies.json](policy_bot/policies.json).

## 1. Run the local checks

From the project directory in WSL, Linux, or macOS, with Python 3.12:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m policy_bot check-mcp
python -m pytest -q
```

`check-mcp` launches the Python MCP SDK's FastMCP server as a separate process, discovers its tool over stdio, and looks up the sample lab prerequisite. It should print `[LAB-101] Students must pass Digital Logic before enrolling in Embedded Systems Lab.`

The local tests use sample PDFs and a real MCP subprocess. Slack API calls and model responses are simulated. The tests cover irrelevant policy queries, valid citation IDs with contradictory claims, duplicate Slack events, Word replies, PDF instructions passed as data, and an MCP timeout.

### Run a demo without AWS credentials

```sh
python -m policy_bot demo
```

This command extracts the sample PDF, simulates the model's tool decision, calls the real MCP server over stdio, and renders the policy citation it received. Its output labels the model responses as scripted.

### Run with a live Groq model

With a Groq API key, you can run the PDF workflow or the Slack bot while AWS account verification is pending. Set the key in your local environment and explicitly select Groq for the command.

```sh
POLICY_BOT_PROVIDER=groq python -m policy_bot ask examples/sample-lab-notice.pdf \
  "What prerequisite do I need for Embedded Systems Lab?"
```

Use `POLICY_BOT_PROVIDER=groq python -m policy_bot` for Slack after following the Slack setup below. The default provider is Bedrock. The Groq option defaults to `openai/gpt-oss-20b` and sends the extracted PDF text and relevant policy passages to Groq. When a question matches a handbook policy's topic and intent, the bot runs the MCP lookup using the original question before calling Groq. It supplies the policy excerpt and requires a matching citation in the reply. Groq can request its own lookup for other questions. Use the supplied fictional notice and policy data for the demo.

With `GROQ_API_KEY` set, run these opt-in tests to make real model calls with both the normal PDF and a PDF containing instructions to skip the lookup, make a false claim, and emit a marker in the answer.

```sh
RUN_LIVE_GROQ=1 python -m pytest -q tests/test_live_groq.py
```

The tests expect the answer to cite `LAB-101` and name the Digital Logic prerequisite. Run them again if you change the model or prompt.

## 2. Test against Bedrock

Use an authenticated AWS CLI profile or other standard AWS credentials. The defaults are `us-east-1` and Amazon Nova Lite. You can select another directly invocable foundation model that supports Converse tool use by setting `AWS_REGION` and `BEDROCK_MODEL_ID`. Your local IAM identity needs `bedrock:InvokeModel` for the chosen model.

```sh
cp .env.example .env
python -m policy_bot check-bedrock
python -m policy_bot ask examples/sample-lab-notice.pdf \
  "What prerequisite do I need for Embedded Systems Lab?"
```

The second command should request `search_academic_policy` and cite `[LAB-101]`. Try “When does registration open?” as a second check. That answer is on page one of the PDF and should cite `[notice:p1]`.

[Bedrock Converse tool-use guide](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html)

## 3. Connect Slack

1. In [Slack's app manager](https://api.slack.com/apps), create an app **From a manifest** in your test workspace. Paste [slack-manifest.yml](slack-manifest.yml) and install the app to the workspace.
2. In **Basic Information → App-Level Tokens**, generate an app-level token with `connections:write`. Put it in `SLACK_APP_TOKEN` in your local `.env`.
3. In **OAuth & Permissions**, copy the Bot User OAuth Token to `SLACK_BOT_TOKEN` in `.env`.
4. If updating an existing installation, add the `files:write` bot scope and reinstall the app to the workspace. Run `python -m policy_bot` or set `POLICY_BOT_PROVIDER=groq` for that command.
5. In Slack, open the app's Messages tab. Attach [examples/sample-lab-notice.pdf](examples/sample-lab-notice.pdf) and include “What prerequisite do I need for Embedded Systems Lab?” in the same message. Look for a thread reply with `[LAB-101]`, its excerpt, and `academic-policy-answer.docx`.
6. Try the same question with [examples/sample-injection-notice.pdf](examples/sample-injection-notice.pdf). The expected answer still names Digital Logic and cites `[LAB-101]`.

The bot accepts Slack-hosted, text-based PDFs up to 2 MB and 12 pages. It validates citation IDs against the sources available for the request and displays their excerpts in the text reply and Word file. Readers can compare the answer with the excerpts to assess whether they support the claims. The logs record request IDs, tool names, and counts without printing document text or tokens. The single worker keeps a bounded in-memory record of recent Slack event IDs for duplicate delivery.

[Slack Socket Mode setup](https://docs.slack.dev/tools/python-slack-sdk/socket-mode/)

## 4. Deploy to ECS Fargate

You need the AWS CLI, Docker with Buildx, a public subnet with an internet gateway route, and an AWS identity that can create the stack. Use the same region for ECR, ECS, the secret, and Bedrock.

In Secrets Manager, create a JSON secret with the keys `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN`. Use the default Secrets Manager encryption key with the provided task policy and note the full secret ARN.

Push the worker image. Create the repository once or reuse it on later deployments. Pick a new image tag when shipping a new build.

```sh
export AWS_REGION=us-east-1
account_id=$(aws sts get-caller-identity --query Account --output text)
registry="$account_id.dkr.ecr.$AWS_REGION.amazonaws.com"
image_uri="$registry/slack-policy-bot:v1"

aws ecr create-repository --repository-name slack-policy-bot --region "$AWS_REGION"
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$registry"
docker buildx build --platform linux/amd64 --tag "$image_uri" --push .
```

Use your own VPC, subnet, and secret ARN in the deployment command.

```sh
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --template-file deploy/ecs.yml \
  --stack-name slack-policy-bot \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ImageUri="$image_uri" \
    VpcId=vpc-REPLACE \
    PublicSubnetId=subnet-REPLACE \
    SlackTokensSecretArn=arn:aws:secretsmanager:REGION:ACCOUNT:secret:REPLACE
```

Stop the local bot so only Fargate handles your next DM. Get the CloudWatch log group name and tail it during the demo:

```sh
log_group=$(aws cloudformation describe-stacks --region "$AWS_REGION" \
  --stack-name slack-policy-bot \
  --query "Stacks[0].Outputs[?OutputKey=='LogGroupName'].OutputValue | [0]" \
  --output text)
aws logs tail "$log_group" --region "$AWS_REGION" --follow
```

Show the Slack reply and look for the same request ID on the `slack=pdf`, `bedrock=tool_use`, `mcp=result`, and `slack=reply` log lines. Fargate, the public IPv4 address, and model invocation can incur AWS charges. Delete the demo stack when finished. The ECR repository and the secret were created separately, so review them separately during cleanup.

```sh
aws cloudformation delete-stack --region "$AWS_REGION" --stack-name slack-policy-bot
```
