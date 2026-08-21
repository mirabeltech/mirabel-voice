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
