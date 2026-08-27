"""Tests for the deploy and the wizard, without touching AWS.

What is worth testing here is what a mistake would cost: the shape of
the Lambda's permissions, that the package holds the right files, and
that the wizard never prints a token where it should print a name.
"""

import io
import wave
import zipfile

import deploy_relay
import setup_relay

ACCOUNT = "450570023995"
REGION = "us-east-2"


def test_the_package_holds_the_relay_and_its_entry_point():
    bundle = zipfile.ZipFile(io.BytesIO(deploy_relay.build_package()))
    assert set(bundle.namelist()) == {
        "mirabel_relay/__init__.py",
        "mirabel_relay/relay.py",
        "mirabel_relay/handler.py",
        "mirabel_relay/signin.py",
    }


def test_the_package_carries_no_dependencies():
    """The Lambda runtime has boto3, and the rest is the standard library."""
    bundle = zipfile.ZipFile(io.BytesIO(deploy_relay.build_package()))
    assert not [name for name in bundle.namelist() if "dist-info" in name]


def statements(policy):
    return {statement["Sid"]: statement for statement in policy["Statement"]}


def test_the_lambda_may_read_its_three_secrets_and_no_others():
    keys = statements(deploy_relay.role_policy(ACCOUNT, REGION))["ReadItsOwnKeys"]
    assert keys["Action"] == "secretsmanager:GetSecretValue"
    named = [resource.split(":secret:")[1] for resource in keys["Resource"]]
    assert sorted(named) == [
        "mirabel-voice/anthropic-??????",
        "mirabel-voice/openai-??????",
        "mirabel-voice/tokens-??????",
    ]


def test_the_lambda_cannot_reach_secrets_by_prefix():
    """A later mirabel-voice/* secret must not be readable for its name alone."""
    keys = statements(deploy_relay.role_policy(ACCOUNT, REGION))["ReadItsOwnKeys"]
    assert not any(resource.endswith("*") for resource in keys["Resource"])


def test_the_lambda_may_write_only_its_own_logs():
    logs = statements(deploy_relay.role_policy(ACCOUNT, REGION))["WriteItsOwnLogs"]
    assert all(action.startswith("logs:") for action in logs["Action"])
    assert logs["Resource"].endswith("/aws/lambda/mirabel-voice-relay*")


def test_the_lambda_may_create_the_log_group_it_writes_to():
    """A ":*" resource covers the streams but refuses the group itself."""
    logs = statements(deploy_relay.role_policy(ACCOUNT, REGION))["WriteItsOwnLogs"]
    assert "logs:CreateLogGroup" in logs["Action"]
    assert not logs["Resource"].endswith(":*")


def test_the_lambda_may_do_nothing_else():
    policy = deploy_relay.role_policy(ACCOUNT, REGION)
    assert len(policy["Statement"]) == 2
    assert all(statement["Effect"] == "Allow" for statement in policy["Statement"])


def test_only_lambda_may_wear_the_role():
    principal = deploy_relay.TRUST_POLICY["Statement"][0]["Principal"]
    assert principal == {"Service": "lambda.amazonaws.com"}


def test_the_smoke_clip_is_audio_a_provider_will_accept():
    clip = wave.open(io.BytesIO(deploy_relay._silence()))
    assert clip.getnchannels() == 1
    assert clip.getframerate() == 16_000
    assert clip.getnframes() / clip.getframerate() > 0.1


def test_the_smoke_upload_carries_the_model_and_the_file():
    body, content_type = deploy_relay._multipart(
        {"model": "whisper-1"}, "smoke.wav", b"RIFFfake"
    )
    assert "multipart/form-data; boundary=" in content_type
    assert b'name="model"' in body and b"whisper-1" in body
    assert b'filename="smoke.wav"' in body and b"RIFFfake" in body


def test_the_holder_list_names_people_and_never_tokens():
    tokens = {"secret-token-aaa": "tommy", "secret-token-bbb": "priya"}
    assert setup_relay.holders_of(tokens) == ["priya", "tommy"]


def test_every_token_is_long_enough_to_be_unguessable():
    assert setup_relay.TOKEN_LENGTH >= 24


def test_the_smoke_test_reuses_its_own_token():
    tokens = {"token-aaa": "tommy", "token-bbb": deploy_relay.SMOKE_HOLDER}
    token, changed = deploy_relay.smoke_token_from(tokens)
    assert token == "token-bbb"
    assert changed is None


def test_the_smoke_test_never_borrows_a_persons_token():
    """A deploy's test calls must not be charged to a person in the
    usage report, so a list without a smoke token grows one."""
    token, changed = deploy_relay.smoke_token_from({"token-aaa": "tommy"})
    assert token != "token-aaa"
    assert changed["token-aaa"] == "tommy"
    assert changed[token] == deploy_relay.SMOKE_HOLDER
    assert len(token) >= 24


SECRET_NAMES = {
    "MIRABEL_OPENAI_SECRET",
    "MIRABEL_ANTHROPIC_SECRET",
    "MIRABEL_TOKENS_SECRET",
}


def test_the_google_flags_reach_the_environment():
    variables = deploy_relay.environment_variables("12345-mirabel.apps", "mirabeltech.com")
    assert variables["MIRABEL_GOOGLE_CLIENT_ID"] == "12345-mirabel.apps"
    assert variables["MIRABEL_GOOGLE_DOMAIN"] == "mirabeltech.com"
    assert SECRET_NAMES <= set(variables)


def test_a_deploy_without_the_flags_keeps_sign_in_on():
    """Once configured, a plain redeploy must never quietly turn
    sign-in off."""
    deployed = {
        "MIRABEL_GOOGLE_CLIENT_ID": "12345-mirabel.apps",
        "MIRABEL_GOOGLE_DOMAIN": "mirabeltech.com",
    }
    variables = deploy_relay.environment_variables(None, None, deployed)
    assert variables["MIRABEL_GOOGLE_CLIENT_ID"] == "12345-mirabel.apps"
    assert variables["MIRABEL_GOOGLE_DOMAIN"] == "mirabeltech.com"


def test_before_sign_in_the_environment_is_the_three_secret_names():
    assert set(deploy_relay.environment_variables(None, None)) == SECRET_NAMES


def test_the_flags_replace_what_was_deployed_before():
    deployed = {"MIRABEL_GOOGLE_CLIENT_ID": "old", "MIRABEL_GOOGLE_DOMAIN": "old.com"}
    variables = deploy_relay.environment_variables("new-id", "new.com", deployed)
    assert variables["MIRABEL_GOOGLE_CLIENT_ID"] == "new-id"
    assert variables["MIRABEL_GOOGLE_DOMAIN"] == "new.com"


def test_the_endorsement_arrives_by_flag_and_is_kept_by_later_deploys():
    variables = deploy_relay.environment_variables(
        None, None, update=("0.6.0", "abc123")
    )
    assert variables["MIRABEL_UPDATE_VERSION"] == "0.6.0"
    assert variables["MIRABEL_UPDATE_HASH"] == "abc123"

    carried = deploy_relay.environment_variables(None, None, variables)
    assert carried["MIRABEL_UPDATE_VERSION"] == "0.6.0"
    assert carried["MIRABEL_UPDATE_HASH"] == "abc123"


def test_a_new_endorsement_replaces_the_carried_one():
    deployed = {"MIRABEL_UPDATE_VERSION": "0.5.0", "MIRABEL_UPDATE_HASH": "old"}
    variables = deploy_relay.environment_variables(
        None, None, deployed, update=("0.6.0", "new")
    )
    assert variables["MIRABEL_UPDATE_VERSION"] == "0.6.0"
    assert variables["MIRABEL_UPDATE_HASH"] == "new"
