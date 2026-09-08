"""Prepare or apply narrowly scoped Mirabel operations resources. Default: plan only."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = "mirabel-voice-relay"
MONITOR = "mirabel-voice-monitor"
TABLE = "mirabel-voice-rate-limits"
TOPIC = "mirabel-voice-alerts"
NAMESPACE = "MirabelVoice/Operations"


def validate(config):
    if type(config["requests_per_person_per_minute"]) is not int or not 1 <= config["requests_per_person_per_minute"] <= 1000:
        raise ValueError("Invalid request limit")
    if type(config["reserved_concurrency"]) is not int or not 1 <= config["reserved_concurrency"] <= 100:
        raise ValueError("Invalid concurrency limit")
    if not 0 < config["aws_reserve_usd"] < config["monthly_target_usd"]:
        raise ValueError("AWS reserve must be below the total target")
    warnings = config["warning_usd"]
    if not warnings or warnings != sorted(set(warnings)) or warnings[-1] != config["monthly_target_usd"]:
        raise ValueError("Warnings must increase to the monthly target")
    if not config["emails"] or len(config["emails"]) > 10 or any("@" not in e for e in config["emails"]):
        raise ValueError("Supply alert recipients")
    return config


def policy(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def allow(actions, resources, **extra):
    return {"Effect": "Allow", "Action": actions, "Resource": resources, **extra}


def required_permissions(account, region):
    base = f"arn:aws"
    return policy([
        allow(["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:CreateFunction",
               "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
               "lambda:GetFunctionConcurrency", "lambda:PutFunctionConcurrency",
               "lambda:DeleteFunctionConcurrency", "lambda:AddPermission", "lambda:GetPolicy",
               "lambda:GetFunctionUrlConfig", "lambda:InvokeFunction"],
              [f"{base}:lambda:{region}:{account}:function:{name}" for name in (FUNCTION, MONITOR)]),
        allow(["lambda:GetAccountSettings"], "*"),
        allow(["dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTimeToLive",
               "dynamodb:DescribeTimeToLive"], f"{base}:dynamodb:{region}:{account}:table/{TABLE}"),
        allow(["sns:CreateTopic", "sns:GetTopicAttributes", "sns:ListSubscriptionsByTopic",
               "sns:Subscribe", "sns:Publish"],
              f"{base}:sns:{region}:{account}:{TOPIC}"),
        allow(["cloudwatch:PutMetricAlarm", "cloudwatch:DescribeAlarms"],
              f"{base}:cloudwatch:{region}:{account}:alarm:mirabel-voice-*"),
        allow(["events:PutRule", "events:DescribeRule", "events:PutTargets", "events:DisableRule"],
              f"{base}:events:{region}:{account}:rule/mirabel-voice-*"),
        allow(["iam:CreateRole", "iam:GetRole", "iam:PutRolePolicy", "iam:GetRolePolicy"],
              [f"{base}:iam::{account}:role/{name}-role" for name in (FUNCTION, MONITOR)]),
        allow(["iam:PassRole"], f"{base}:iam::{account}:role/{MONITOR}-role",
              Condition={"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}),
        allow(["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
              [f"{base}:logs:{region}:{account}:log-group:/aws/lambda/{MONITOR}",
               f"{base}:logs:{region}:{account}:log-group:/aws/lambda/{MONITOR}:*"]),
        allow(["budgets:ViewBudget", "budgets:ModifyBudget"],
              f"{base}:budgets::{account}:budget/mirabel-voice-infrastructure"),
    ])


def alarms(config, topic):
    def alarm(suffix, metric, threshold, *, namespace=NAMESPACE, period=900,
              evaluation=2, datapoints=2, stat="Maximum", missing="breaching",
              recovery=True, dimensions=None):
        return dict(AlarmName="mirabel-voice-" + suffix,
            AlarmDescription="Mirabel Voice: " + suffix + ". See the operations runbook.",
            Namespace=namespace, MetricName=metric, Statistic=stat,
            Dimensions=dimensions or [], Period=period, EvaluationPeriods=evaluation,
            DatapointsToAlarm=datapoints, Threshold=threshold,
            ComparisonOperator="GreaterThanOrEqualToThreshold", TreatMissingData=missing,
            AlarmActions=[topic], OKActions=[topic] if recovery else [])
    out = [
        alarm("health", "HealthFailed", 1),
        alarm("slow", "SyntheticLatency", 15000, missing="notBreaching"),
        alarm("spend-monitor", "SpendFailed", 1, period=3600),
        alarm("unpriced-usage", "UnpricedRequests", 1, period=3600),
        alarm("stale-prices", "PricingAgeDays", 30, period=3600, recovery=False),
    ]
    for threshold in config["warning_usd"]:
        out.append(alarm("estimated-budget-" + str(threshold), "EstimatedUSDWithAWSReserve",
                         threshold, period=3600, evaluation=1, datapoints=1,
                         recovery=False, missing="notBreaching"))
    dims = [{"Name": "FunctionName", "Value": FUNCTION}]
    for suffix, metric in [("relay-errors", "Errors"), ("relay-throttles", "Throttles")]:
        out.append(alarm(suffix, metric, 3, namespace="AWS/Lambda", period=300,
                         stat="Sum", missing="notBreaching", dimensions=dims))
    return out


def package_monitor(audio):
    with wave.open(str(audio), "rb") as wav:
        if not 0 < wav.getnframes() / wav.getframerate() <= 10:
            raise ValueError("Synthetic speech must be at most 10 seconds")
    stream = io.BytesIO()
    prices = json.loads((ROOT / "docs/pricing.json").read_text())
    prices["cleanup_per_million_tokens"]["claude-haiku-4-5-20251001"] = prices["cleanup_per_million_tokens"]["claude-haiku-4-5"]
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "operations/monitor.py", "monitor.py")
        archive.write(audio, "synthetic.wav")
        archive.writestr("pricing.json", json.dumps(prices))
    return stream.getvalue()


def code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)


def preflight(session, account, config):
    """Read specific resources; fail before any writes when permissions are absent."""
    checks = [
        ("lambda:GetFunctionConfiguration", lambda: session.client("lambda").get_function_configuration(FunctionName=FUNCTION)),
        ("lambda:GetFunctionConcurrency", lambda: session.client("lambda").get_function_concurrency(FunctionName=FUNCTION)),
        ("lambda:GetAccountSettings", lambda: session.client("lambda").get_account_settings()),
        ("dynamodb:DescribeTable", lambda: session.client("dynamodb").describe_table(TableName=TABLE)),
        ("cloudwatch:DescribeAlarms", lambda: session.client("cloudwatch").describe_alarms(AlarmNamePrefix="mirabel-voice-")),
        ("sns:GetTopicAttributes", lambda: session.client("sns").get_topic_attributes(TopicArn=f"arn:aws:sns:{config['region']}:{account}:{TOPIC}")),
        ("events:DescribeRule", lambda: session.client("events").describe_rule(Name=MONITOR+"-health")),
        ("iam:GetRole", lambda: session.client("iam").get_role(RoleName=MONITOR+"-role")),
        ("budgets:ViewBudget", lambda: session.client("budgets").describe_budget(AccountId=account, BudgetName="mirabel-voice-infrastructure")),
    ]
    errors = []
    for action, check in checks:
        try:
            check()
        except Exception as error:
            if code(error) not in {"ResourceNotFoundException", "NotFound", "NotFoundException", "NoSuchEntity"}:
                errors.append({"action": action, "error": code(error)})
    if errors:
        return errors
    limits = session.client("lambda").get_account_settings()["AccountLimit"]
    old = session.client("lambda").get_function_concurrency(FunctionName=FUNCTION).get("ReservedConcurrentExecutions", 0)
    if config["reserved_concurrency"] > limits["UnreservedConcurrentExecutions"] + old - 100:
        raise ValueError("AWS concurrency quota cannot accommodate this reservation")
    return []


def ensure_budget(session, account, config):
    client = session.client("budgets")
    budget = dict(BudgetName="mirabel-voice-infrastructure", BudgetLimit={
        "Amount": str(config["aws_reserve_usd"]), "Unit": "USD"},
        TimeUnit="MONTHLY", BudgetType="COST")
    subscribers = [{"SubscriptionType": "EMAIL", "Address": email} for email in config["emails"]]
    notifications = [{"Notification": dict(NotificationType="ACTUAL",
        ComparisonOperator="GREATER_THAN", Threshold=n, ThresholdType="PERCENTAGE"),
        "Subscribers": subscribers} for n in (50, 80, 100)]
    try:
        client.describe_budget(AccountId=account, BudgetName=budget["BudgetName"])
    except client.exceptions.NotFoundException:
        client.create_budget(AccountId=account, Budget=budget, NotificationsWithSubscribers=notifications)
        return
    # Preserve additional existing recipients, but ensure every requested one is present.
    existing = client.describe_budget(AccountId=account, BudgetName=budget["BudgetName"])["Budget"]
    if float(existing["BudgetLimit"]["Amount"]) != config["aws_reserve_usd"]:
        raise ValueError("Existing infrastructure budget differs; review before replacing it")
    current = client.describe_notifications_for_budget(AccountId=account, BudgetName=budget["BudgetName"])["Notifications"]
    for desired in notifications:
        notification = desired["Notification"]
        found = next((n for n in current if all(n.get(k) == v for k, v in notification.items())), None)
        if found is None:
            client.create_notification(AccountId=account, BudgetName=budget["BudgetName"], **desired)
            continue
        subscribed = client.describe_subscribers_for_notification(
            AccountId=account, BudgetName=budget["BudgetName"], Notification=notification)["Subscribers"]
        addresses = {s["Address"] for s in subscribed if s["SubscriptionType"] == "EMAIL"}
        for subscriber in subscribers:
            if subscriber["Address"] not in addresses:
                client.create_subscriber(AccountId=account, BudgetName=budget["BudgetName"],
                                         Notification=notification, Subscriber=subscriber)


def apply(session, account, config, audio, backup_dir):
    import deploy_relay
    region = config["region"]
    lam, iam, sns = (session.client(n) for n in ("lambda", "iam", "sns"))
    ddb, events, cw = (session.client(n) for n in ("dynamodb", "events", "cloudwatch"))
    table_arn = f"arn:aws:dynamodb:{region}:{account}:table/{TABLE}"
    # Back up the live relay before any deployment; these files stay private.
    backup_dir.mkdir(parents=True, exist_ok=False)
    old = lam.get_function(FunctionName=FUNCTION)
    previous = old["Configuration"]
    previous_concurrency = lam.get_function_concurrency(FunctionName=FUNCTION)
    with urllib.request.urlopen(old["Code"]["Location"], timeout=30) as response:
        old_zip = response.read()
    (backup_dir / "relay.zip").write_bytes(old_zip)
    (backup_dir / "configuration.json").write_text(json.dumps(previous, default=str))
    (backup_dir / "concurrency.json").write_text(json.dumps(previous_concurrency))
    try:
        ddb.describe_table(TableName=TABLE)
    except ddb.exceptions.ResourceNotFoundException:
        ddb.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName":"pk","AttributeType":"S"}],
            KeySchema=[{"AttributeName":"pk","KeyType":"HASH"}])
        ddb.get_waiter("table_exists").wait(TableName=TABLE)
    ttl = ddb.describe_time_to_live(TableName=TABLE)["TimeToLiveDescription"]
    if ttl.get("TimeToLiveStatus") == "DISABLED":
        ddb.update_time_to_live(TableName=TABLE, TimeToLiveSpecification={"Enabled":True,"AttributeName":"expires"})
    iam.put_role_policy(RoleName=FUNCTION+"-role", PolicyName="mirabel-voice-rate-limit",
        PolicyDocument=json.dumps(policy([allow(["dynamodb:UpdateItem"],table_arn)])))
    topic = sns.create_topic(Name=TOPIC)["TopicArn"]
    subscriptions = sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=topic)
    present = {sub["Endpoint"] for page in subscriptions for sub in page["Subscriptions"] if sub["Protocol"] == "email"}
    for email in config["emails"]:
        if email not in present:
            sns.subscribe(TopicArn=topic, Protocol="email", Endpoint=email, ReturnSubscriptionArn=True)
    for alarm in alarms(config, topic):
        cw.put_metric_alarm(**alarm)
    ensure_budget(session, account, config)
    role_name = MONITOR+"-role"
    try:
        monitor_role = iam.get_role(RoleName=role_name)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        monitor_role = iam.create_role(RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(deploy_relay.TRUST_POLICY))["Role"]["Arn"]
    token_secret = previous.get("Environment",{}).get("Variables",{}).get("MIRABEL_TOKENS_SECRET", deploy_relay.TOKENS_SECRET)
    iam.put_role_policy(RoleName=role_name, PolicyName=MONITOR, PolicyDocument=json.dumps(policy([
        allow(["logs:CreateLogStream","logs:PutLogEvents"], f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{MONITOR}:*"),
        allow(["logs:FilterLogEvents"],f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{FUNCTION}:*"),
        allow(["secretsmanager:GetSecretValue"],f"arn:aws:secretsmanager:{region}:{account}:secret:{token_secret}-*"),
        allow(["cloudwatch:PutMetricData"],"*",Condition={"StringEquals":{"cloudwatch:namespace":NAMESPACE}}),
    ])))
    logs = session.client("logs")
    try:
        logs.create_log_group(logGroupName="/aws/lambda/"+MONITOR)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_retention_policy(logGroupName="/aws/lambda/"+MONITOR, retentionInDays=30)
    relay_url = lam.get_function_url_config(FunctionName=FUNCTION)["FunctionUrl"].rstrip("/")
    monitor_env = {"RELAY_URL":relay_url,"TOKENS_SECRET":token_secret,"AWS_RESERVE_USD":str(config["aws_reserve_usd"])}
    package = package_monitor(audio)
    try:
        lam.get_function(FunctionName=MONITOR)
    except lam.exceptions.ResourceNotFoundException:
        time.sleep(10)  # allow the new role's trust/permissions to propagate
        lam.create_function(FunctionName=MONITOR,Runtime="python3.12",Role=monitor_role,
            Handler="monitor.lambda_handler",Timeout=120,MemorySize=256,
            Code={"ZipFile":package},Environment={"Variables":monitor_env})
        lam.get_waiter("function_active_v2").wait(FunctionName=MONITOR)
    else:
        lam.update_function_code(FunctionName=MONITOR,ZipFile=package)
        lam.get_waiter("function_updated_v2").wait(FunctionName=MONITOR)
        lam.update_function_configuration(FunctionName=MONITOR,Environment={"Variables":monitor_env})
        lam.get_waiter("function_updated_v2").wait(FunctionName=MONITOR)
    changed = False
    try:
        deployed = lam.update_function_code(FunctionName=FUNCTION,ZipFile=deploy_relay.build_package(),
                                            RevisionId=previous["RevisionId"])
        changed = True
        revision = deployed["RevisionId"]
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
        env = dict(previous.get("Environment",{}).get("Variables",{}))
        env.update(MIRABEL_RATE_LIMIT_TABLE=TABLE,
                   MIRABEL_REQUESTS_PER_MINUTE=str(config["requests_per_person_per_minute"]))
        configured = lam.update_function_configuration(FunctionName=FUNCTION,Environment={"Variables":env},
                                                       RevisionId=revision)
        revision = configured["RevisionId"]
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
        lam.put_function_concurrency(FunctionName=FUNCTION,ReservedConcurrentExecutions=config["reserved_concurrency"])
        # Do not schedule recurring checks until both one-off checks pass.
        for kind in ("health","spend"):
            response = lam.invoke(FunctionName=MONITOR,Payload=json.dumps({"kind":kind}).encode())
            result = json.loads(response["Payload"].read())
            if response.get("FunctionError") or result.get("ok") is not True:
                raise RuntimeError("Deployed monitor check failed: "+kind)
        for kind, schedule in (("health","rate(15 minutes)"),("spend","rate(1 hour)")):
            name = MONITOR+"-"+kind
            rule = events.put_rule(Name=name,ScheduleExpression=schedule,State="DISABLED")["RuleArn"]
            try:
                lam.add_permission(FunctionName=MONITOR,StatementId=name,Action="lambda:InvokeFunction",
                    Principal="events.amazonaws.com",SourceArn=rule,SourceAccount=account)
            except lam.exceptions.ResourceConflictException:
                pass
            result = events.put_targets(Rule=name,Targets=[{"Id":"monitor",
                "Arn":f"arn:aws:lambda:{region}:{account}:function:{MONITOR}",
                "Input":json.dumps({"kind":kind}),"RetryPolicy":{"MaximumRetryAttempts":0,"MaximumEventAgeInSeconds":60}}])
            if result["FailedEntryCount"]:
                raise RuntimeError("Could not attach schedule")
            events.put_rule(Name=name,ScheduleExpression=schedule,State="ENABLED")
    except Exception:
        for kind in ("health","spend"):
            try: events.disable_rule(Name=MONITOR+"-"+kind)
            except events.exceptions.ResourceNotFoundException: pass
        if changed:
            restored = lam.update_function_code(FunctionName=FUNCTION,ZipFile=old_zip, RevisionId=revision)
            lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
            lam.update_function_configuration(FunctionName=FUNCTION,Environment=previous.get("Environment",{"Variables":{}}),
                                              RevisionId=restored["RevisionId"])
            lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
            if "ReservedConcurrentExecutions" in previous_concurrency:
                lam.put_function_concurrency(FunctionName=FUNCTION,ReservedConcurrentExecutions=previous_concurrency["ReservedConcurrentExecutions"])
            else:
                lam.delete_function_concurrency(FunctionName=FUNCTION)
        raise
    return {"configured":True,"email_confirmation_required":True,"backup_directory":str(backup_dir)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--audio",type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--output",type=Path,default=ROOT/"build_probe/operations-plan")
    args=parser.parse_args()
    import boto3
    config=validate(json.loads(args.config.read_text()))
    session=boto3.Session(profile_name=args.profile,region_name=config["region"])
    account=session.client("sts").get_caller_identity()["Account"]
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"administrator-permissions.json").write_text(json.dumps(required_permissions(account,config["region"]),indent=2))
    failures=preflight(session,account,config)
    report={"ready":not failures,"missing_access":failures,"monthly_target":config["monthly_target_usd"],
            "hard_spend_cap":False,"alert_count":len(alarms(config,"preview-topic"))}
    (args.output/"preflight.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    if not args.apply:
        return 0 if not failures else 2
    if failures:
        return 2
    if not args.audio:
        parser.error("--apply requires a synthetic speech --audio fixture")
    print(json.dumps(apply(session,account,config,args.audio,
                           args.output/("backup-"+str(int(time.time()))))))
    return 0


if __name__=="__main__":
    sys.exit(main())
