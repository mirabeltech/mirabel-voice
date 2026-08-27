"""Deploy the relay to AWS. Run it again to update it.

    python scripts/deploy_relay.py

The script owns everything that can be scripted: the Lambda's execution
role and its narrow permissions, the function, its Function URL, and a
smoke test that proves the deployed relay answers a real dictation and
refuses an unknown token. Nothing here needs the console. Running it a
second time updates what exists instead of creating a duplicate, so it
is the only way the relay is ever changed.

What it does NOT do is create the two provider-key secrets. Those are
the account owner's job, done once by hand, so the keys go from the
provider dashboards into AWS without passing through a script. See
docs/AWS.md. The token list is the wizard's job; see setup_relay.py.

The deploy ends by printing cold and warm latency for the deployed
relay, which is the evidence the 1-2 second dictation target is
measured against.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import wave
import zipfile
from pathlib import Path

FUNCTION = "mirabel-voice-relay"
ROLE = "mirabel-voice-relay-role"
DEFAULT_REGION = "us-east-2"
RUNTIME = "python3.12"
ENTRY = "mirabel_relay.handler.lambda_handler"

# A five-minute recording has to be transcribed before this runs out.
TIMEOUT_SECONDS = 120
MEMORY_MB = 512

OPENAI_SECRET = "mirabel-voice/openai"
ANTHROPIC_SECRET = "mirabel-voice/anthropic"
TOKENS_SECRET = "mirabel-voice/tokens"

# The smoke test's own holder name. Its calls must never land on a
# person's token, or the usage report charges deploys to that person.
SMOKE_HOLDER = "Smoke test"

SOURCE = Path(__file__).resolve().parent.parent / "src" / "mirabel_relay"
PACKAGED = ("__init__.py", "relay.py", "handler.py", "signin.py")

GOOGLE_VARIABLES = ("MIRABEL_GOOGLE_CLIENT_ID", "MIRABEL_GOOGLE_DOMAIN")
UPDATE_VARIABLES = ("MIRABEL_UPDATE_VERSION", "MIRABEL_UPDATE_HASH")
ARCHIVE_BASE = "https://github.com/mirabeltech/mirabel-voice/archive/refs/tags"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


class Stop(Exception):
    """Something needs a person. The message says what."""


def say(message: str = "") -> None:
    print(message, flush=True)


def main(argv=None) -> int:
    parsed = _arguments(argv)
    try:
        session = open_session(parsed.profile, parsed.region)
        account = _identity(session)
        say(f"Account {account}, region {parsed.region}.")
        _require_provider_secrets(session)
        if bool(parsed.google_client_id) != bool(parsed.google_domain):
            raise Stop(
                "Google sign-in needs both --google-client-id and "
                "--google-domain. Pass both, or neither."
            )
        update = None
        if parsed.endorse:
            update = endorsed_update(parsed.endorse)
            say(f"Endorsing {update[0]} (content hash {update[1][:12]}...).")
        role_arn = ensure_role(session, account, parsed.region)
        package = build_package()
        say(f"Packaged {len(package):,} bytes from {len(PACKAGED)} files.")
        ensure_function(
            session, package, role_arn,
            parsed.google_client_id, parsed.google_domain,
            update,
        )
        url = ensure_function_url(session)
        say(f"The relay answers at {url}")
        if parsed.no_smoke:
            say("Smoke test skipped.")
            return 0
        return smoke_test(session, url, expect_endorsement=bool(parsed.endorse))
    except Stop as reason:
        say()
        say(f"Stopped: {reason}")
        return 1


def _arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="AWS profile name. Default: the usual one.")
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"Region for everything. Default: {DEFAULT_REGION}.",
    )
    parser.add_argument(
        "--no-smoke", action="store_true", help="Deploy without the live test calls."
    )
    parser.add_argument(
        "--google-client-id",
        help="Our Google OAuth client id. Set once with --google-domain; "
        "later deploys keep it without the flag.",
    )
    parser.add_argument(
        "--google-domain",
        help="The Mirabel Workspace domains for the sign-in check, "
        "comma separated when the org answers to more than one.",
    )
    parser.add_argument(
        "--endorse",
        metavar="TAG",
        help="The release every machine should self-update to, e.g. "
        "v0.5.0. The hash is computed from the tag's own source. "
        "Later deploys keep the endorsement without the flag.",
    )
    return parser.parse_args(argv)


def endorsed_update(tag: str) -> tuple[str, str]:
    """Fetch the tag's source from GitHub and hash what machines install.

    The hash covers the package folder's contents, computed by the same
    content_hash the app runs on what it downloads. Hashing the zip
    itself would break the day GitHub changes its compression.
    """
    import tempfile
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from mirabel_voice.updater import content_hash

    tag = tag if tag.startswith("v") else "v" + tag
    url = f"{ARCHIVE_BASE}/{tag}.zip"
    try:
        with urllib.request.urlopen(url, timeout=60) as reply:  # noqa: S310
            archive = reply.read()
    except urllib.error.HTTPError as refusal:
        raise Stop(
            f"GitHub answered {refusal.code} for {tag}. Is the release "
            "published? Tags appear at github.com/mirabeltech/"
            "mirabel-voice/releases."
        ) from refusal
    with tempfile.TemporaryDirectory(prefix="mirabel-endorse-") as work:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(work)
        package = next(
            (
                parent / "mirabel_voice"
                for parent in Path(work).glob("*/src")
                if (parent / "mirabel_voice" / "__init__.py").exists()
            ),
            None,
        )
        if package is None:
            raise Stop(f"The {tag} archive holds no mirabel_voice package.")
        return tag.lstrip("v"), content_hash(package)


def open_session(profile: str | None, region: str):
    """Open an AWS session, or explain why the credentials will not do."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError
    except ImportError:
        raise Stop("boto3 is not installed. Run:  pip install -e .[dev]") from None
    try:
        return boto3.Session(profile_name=profile or None, region_name=region)
    except BotoCoreError as failure:
        raise Stop(
            f"AWS could not use that profile. Check 'aws configure list'. ({failure})"
        ) from failure


def _identity(session) -> str:
    """Prove the credentials work before anything is created."""
    try:
        return session.client("sts").get_caller_identity()["Account"]
    except Exception as failure:  # noqa: BLE001 - any failure here means no credentials
        raise Stop(
            "AWS did not accept these credentials. Run 'aws configure' first, "
            f"or pass --profile.  ({failure})"
        ) from failure


def _denied(failure) -> str | None:
    """Return the missing action, if this failure is a permissions one."""
    error = getattr(failure, "response", {}).get("Error", {})
    if error.get("Code") in {"AccessDenied", "AccessDeniedException",
                             "UnauthorizedOperation"}:
        return error.get("Message", "")
    return None


def _attempt(what: str, call, *args, **kwargs):
    """Run one AWS call, turning a denial into an answerable request."""
    from botocore.exceptions import ClientError

    try:
        return call(*args, **kwargs)
    except ClientError as failure:
        message = _denied(failure)
        if message is None:
            raise
        raise Stop(
            f"AWS refused {what}.\n\n"
            f"    {message}\n\n"
            "The deploy user is missing that action. Add it to the inline "
            "policy on the user (docs/deploy-policy.json) and run this again."
        ) from failure


def _require_provider_secrets(session) -> None:
    """Fail early and clearly if the owner's two secrets are not there."""
    from botocore.exceptions import ClientError

    secrets = session.client("secretsmanager")
    for name in (OPENAI_SECRET, ANTHROPIC_SECRET):
        try:
            _attempt(f"reading the secret {name}", secrets.describe_secret,
                     SecretId=name)
        except ClientError as failure:
            if failure.response["Error"]["Code"] == "ResourceNotFoundException":
                raise Stop(
                    f"The secret {name} does not exist in this region.\n"
                    "The account owner creates both provider-key secrets by "
                    "hand; see docs/AWS.md step 5. Check the region too: a "
                    "secret made in another region is invisible here."
                ) from failure
            raise


def role_policy(account: str, region: str) -> dict:
    """What the Lambda may do: read its three secrets, write its own logs.

    Nothing else. The secrets are named one by one rather than matched
    by pattern, so a later secret under the same prefix is not readable
    by the relay just for being named similarly.
    """
    prefix = f"arn:aws:secretsmanager:{region}:{account}:secret:"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadItsOwnKeys",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                # The trailing wildcard covers the six random characters
                # AWS appends to every secret ARN. The name is exact.
                "Resource": [
                    f"{prefix}{OPENAI_SECRET}-??????",
                    f"{prefix}{ANTHROPIC_SECRET}-??????",
                    f"{prefix}{TOKENS_SECRET}-??????",
                ],
            },
            {
                "Sid": "WriteItsOwnLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                # The trailing star with no colon before it covers both
                # the log group itself and the streams inside it. With
                # ":*" instead, creating the group is refused and the
                # relay runs but never writes a usage line.
                "Resource": (
                    f"arn:aws:logs:{region}:{account}:log-group:"
                    f"/aws/lambda/{FUNCTION}*"
                ),
            },
        ],
    }


def ensure_role(session, account: str, region: str) -> str:
    """Create the execution role, or bring an existing one back in line."""
    from botocore.exceptions import ClientError

    iam = session.client("iam")
    try:
        role = _attempt("reading the relay role", iam.get_role, RoleName=ROLE)
        arn = role["Role"]["Arn"]
        say(f"The role {ROLE} exists.")
    except ClientError as failure:
        if failure.response["Error"]["Code"] != "NoSuchEntity":
            raise
        made = _attempt(
            "creating the relay role",
            iam.create_role,
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
            Description="Lets the Mirabel Voice relay read its keys and log.",
        )
        arn = made["Role"]["Arn"]
        say(f"Created the role {ROLE}.")

    _attempt(
        "writing the relay role's permissions",
        iam.put_role_policy,
        RoleName=ROLE,
        PolicyName="mirabel-voice-relay",
        PolicyDocument=json.dumps(role_policy(account, region)),
    )
    say("The role may read its three secrets and write its own logs. Nothing else.")
    return arn


def build_package() -> bytes:
    """Zip the relay's source. There is nothing to compile and nothing to vendor."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in PACKAGED:
            source = SOURCE / name
            if not source.exists():
                raise Stop(f"{source} is missing. Deploy from a full checkout.")
            bundle.writestr(f"mirabel_relay/{name}", source.read_text(encoding="utf-8"))
    return buffer.getvalue()


def environment_variables(
    google_client_id: str | None,
    google_domain: str | None,
    existing: dict | None = None,
    update: tuple[str, str] | None = None,
) -> dict:
    """The Lambda's environment: secret names, sign-in, endorsed update.

    The Google values are not secrets, but they are also not in this
    public repository, so they arrive by flag once and are carried
    forward from the deployed function on every later deploy. A deploy
    without the flags must never quietly turn sign-in off. The endorsed
    update travels the same way: --endorse sets it, and every later
    deploy keeps it until the next --endorse moves it.
    """
    variables = {
        "MIRABEL_OPENAI_SECRET": OPENAI_SECRET,
        "MIRABEL_ANTHROPIC_SECRET": ANTHROPIC_SECRET,
        "MIRABEL_TOKENS_SECRET": TOKENS_SECRET,
    }
    if google_client_id and google_domain:
        variables["MIRABEL_GOOGLE_CLIENT_ID"] = google_client_id
        variables["MIRABEL_GOOGLE_DOMAIN"] = google_domain
    elif existing:
        for name in GOOGLE_VARIABLES:
            if existing.get(name):
                variables[name] = existing[name]
    if update:
        variables["MIRABEL_UPDATE_VERSION"] = update[0]
        variables["MIRABEL_UPDATE_HASH"] = update[1]
    elif existing:
        for name in UPDATE_VARIABLES:
            if existing.get(name):
                variables[name] = existing[name]
    return variables


def ensure_function(
    session,
    package: bytes,
    role_arn: str,
    google_client_id: str | None = None,
    google_domain: str | None = None,
    update: tuple[str, str] | None = None,
) -> None:
    """Create the function, or update the one that is already there."""
    from botocore.exceptions import ClientError

    lam = session.client("lambda")
    try:
        deployed = _attempt(
            "reading the relay function", lam.get_function, FunctionName=FUNCTION
        )
    except ClientError as failure:
        if failure.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        environment = {
            "Variables": environment_variables(
                google_client_id, google_domain, update=update
            )
        }
        _create_function(lam, package, role_arn, environment)
        say(f"Created the function {FUNCTION}.")
        return

    already_there = (
        deployed["Configuration"].get("Environment", {}).get("Variables", {})
    )
    environment = {
        "Variables": environment_variables(
            google_client_id, google_domain, already_there, update
        )
    }

    _attempt(
        "updating the relay's code",
        lam.update_function_code,
        FunctionName=FUNCTION,
        ZipFile=package,
    )
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    _attempt(
        "updating the relay's settings",
        lam.update_function_configuration,
        FunctionName=FUNCTION,
        Role=role_arn,
        Handler=ENTRY,
        Runtime=RUNTIME,
        Timeout=TIMEOUT_SECONDS,
        MemorySize=MEMORY_MB,
        Environment=environment,
    )
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    say(f"Updated the function {FUNCTION}.")
    if "MIRABEL_GOOGLE_CLIENT_ID" in environment["Variables"]:
        say("Google sign-in is on: work accounts and tokens both open the door.")
    else:
        say("Google sign-in is not configured yet; tokens only.")
    endorsed = environment["Variables"].get("MIRABEL_UPDATE_VERSION")
    if endorsed:
        say(f"The relay endorses version {endorsed} for self-update.")
    else:
        say("No endorsed update yet; machines follow the newest release.")


def _create_function(lam, package: bytes, role_arn: str, environment: dict) -> None:
    """Create the function, waiting out the new role's propagation delay.

    A role is not usable the instant it is created. AWS answers "cannot
    be assumed" for a few seconds afterwards, which is not a mistake to
    report - it is a wait.
    """
    from botocore.exceptions import ClientError

    deadline = time.monotonic() + 60
    while True:
        try:
            _attempt(
                "creating the relay function",
                lam.create_function,
                FunctionName=FUNCTION,
                Runtime=RUNTIME,
                Role=role_arn,
                Handler=ENTRY,
                Code={"ZipFile": package},
                Timeout=TIMEOUT_SECONDS,
                MemorySize=MEMORY_MB,
                Environment=environment,
                Description="Holds the provider keys so the laptops do not.",
            )
            break
        except ClientError as failure:
            assumable = "cannot be assumed" in str(failure)
            if not assumable or time.monotonic() > deadline:
                raise
            say("Waiting for the new role to become usable...")
            time.sleep(5)
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)


def ensure_function_url(session) -> str:
    """Give the function a public URL. The token, not AWS, is the door."""
    from botocore.exceptions import ClientError

    lam = session.client("lambda")
    try:
        existing = _attempt(
            "reading the relay's URL", lam.get_function_url_config,
            FunctionName=FUNCTION,
        )
        url = existing["FunctionUrl"]
    except ClientError as failure:
        if failure.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        made = _attempt(
            "creating the relay's URL",
            lam.create_function_url_config,
            FunctionName=FUNCTION,
            AuthType="NONE",
        )
        url = made["FunctionUrl"]

    try:
        _attempt(
            "opening the relay's URL",
            lam.add_permission,
            FunctionName=FUNCTION,
            StatementId="public-invoke",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
    except ClientError as failure:
        if failure.response["Error"]["Code"] != "ResourceConflictException":
            raise
    return url.rstrip("/")


def _call(url: str, path: str, token: str, body: bytes, content_type: str):
    """Make one real call to the deployed relay. Returns status and seconds."""
    call = urllib.request.Request(url + path, data=body, method="POST")
    call.add_header("content-type", content_type)
    call.add_header("x-api-key", token)
    if path == "/v1/messages":
        call.add_header("anthropic-version", "2023-06-01")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(call, timeout=120) as reply:
            reply.read()
            status = reply.status
    except urllib.error.HTTPError as refusal:
        detail = refusal.read()
        status = refusal.code
        if status >= 500:
            raise Stop(
                f"The relay answered {status} on {path}:\n\n"
                f"    {detail.decode('utf-8', 'replace')[:500]}\n\n"
                "The relay's own log says more:  aws logs tail "
                f"/aws/lambda/{FUNCTION} --since 5m"
            ) from refusal
    except urllib.error.URLError as unreachable:
        raise Stop(
            f"The relay's URL could not be reached: {unreachable.reason}"
        ) from unreachable
    return status, time.monotonic() - started


def _silence(seconds: float = 0.6) -> bytes:
    """A short silent WAV, so the transcribe route can be proved cheaply."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16_000)
        clip.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buffer.getvalue()


def _multipart(fields: dict, filename: str, payload: bytes):
    """Build the multipart body the OpenAI transcription API expects."""
    boundary = "----mirabelvoicesmoke"
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\""
            f"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(payload)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _get_update(url: str, token: str) -> tuple[int, str]:
    """Ask the deployed relay which release it endorses."""
    call = urllib.request.Request(url + "/update", method="GET")
    call.add_header("x-api-key", token)
    try:
        with urllib.request.urlopen(call, timeout=30) as reply:
            answer = json.loads(reply.read())
            return reply.status, answer.get("version", "?")
    except urllib.error.HTTPError as refusal:
        return refusal.code, ""


def smoke_test(session, url: str, expect_endorsement: bool = False) -> int:
    """Prove the deployed relay works, and measure how fast it answers."""
    say()
    say("Smoke test")
    token = _smoke_token(session)

    refused, _ = _call(
        url, "/v1/messages", "not-a-token",
        json.dumps({"model": "claude-haiku-4-5", "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}]}).encode(),
        "application/json",
    )
    say(f"  unknown token          -> {refused}"
        f"{'  (expected 401)' if refused != 401 else ''}")

    cleanup_body = json.dumps(
        {
            "model": "claude-haiku-4-5",
            "max_tokens": 16,
            "system": "Reply with the single word: ready.",
            "messages": [{"role": "user", "content": "ready"}],
        }
    ).encode()

    cold_status, cold = _call(url, "/v1/messages", token, cleanup_body,
                              "application/json")
    say(f"  cleanup, cold start    -> {cold_status} in {cold * 1000:,.0f} ms")

    warm = []
    for _ in range(3):
        status, seconds = _call(url, "/v1/messages", token, cleanup_body,
                                "application/json")
        warm.append(seconds)
    say(f"  cleanup, warm          -> {status} in "
        f"{min(warm) * 1000:,.0f}-{max(warm) * 1000:,.0f} ms")

    audio_body, audio_type = _multipart(
        {"model": "whisper-1", "language": "en"}, "smoke.wav", _silence()
    )
    audio_status, audio_seconds = _call(
        url, "/v1/audio/transcriptions", token, audio_body, audio_type
    )
    say(f"  transcribe, warm       -> {audio_status} in "
        f"{audio_seconds * 1000:,.0f} ms")

    update_status, endorsed = _get_update(url, token)
    if update_status == 200:
        say(f"  endorsed update        -> {update_status} (version {endorsed})")
    else:
        say(f"  endorsed update        -> {update_status} (none endorsed)")

    ok = refused == 401 and cold_status == 200 and audio_status == 200
    if expect_endorsement and update_status != 200:
        say("  The endorsement was just set but the relay does not serve it.")
        ok = False
    say()
    if ok:
        say("Both keys work through the relay, and an unknown token is refused.")
    else:
        say("Something did not answer as expected. The statuses above say what.")
        say("A 401 on a route with a real token means that provider's key is "
            "wrong; check the secret it came from.")
    return 0 if ok else 1


def smoke_token_from(tokens: dict[str, str]) -> tuple[str, dict[str, str] | None]:
    """Return the smoke test's token, minting one when the list lacks it.

    The second value is the new token list to write back, or None when
    the list already held one. The smoke test used to borrow the first
    person's token, which charged every deploy's test calls to that
    person in the usage report.
    """
    import secrets

    for token, holder in tokens.items():
        if holder == SMOKE_HOLDER:
            return token, None
    minted = secrets.token_urlsafe(24)
    return minted, {**tokens, minted: SMOKE_HOLDER}


def _smoke_token(session) -> str:
    """Fetch the smoke test's token, creating it on first use."""
    from botocore.exceptions import ClientError

    client = session.client("secretsmanager")
    try:
        held = _attempt(
            "reading the token list", client.get_secret_value, SecretId=TOKENS_SECRET
        )
    except ClientError as failure:
        if failure.response["Error"]["Code"] == "ResourceNotFoundException":
            raise Stop(
                f"The secret {TOKENS_SECRET} does not exist yet, so there is no "
                "token to test with.\nRun:  python scripts/setup_relay.py"
            ) from failure
        raise
    token, changed = smoke_token_from(json.loads(held["SecretString"]))
    if changed is not None:
        _attempt(
            "adding the smoke-test token",
            client.put_secret_value,
            SecretId=TOKENS_SECRET,
            SecretString=json.dumps(changed, indent=2, sort_keys=True),
        )
        say(f"  A token for '{SMOKE_HOLDER}' was added to the list.")
    return token


if __name__ == "__main__":
    sys.exit(main())
