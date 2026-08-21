# Setting up AWS for Mirabel Voice

This guide is for the person who creates the AWS account. It lists what
Mirabel Voice needs, and nothing else. Follow it top to bottom; it takes
about half an hour, most of which is waiting for account verification.

## What AWS does for this product

Mirabel Voice sends speech to OpenAI and text to Anthropic. Today, every
user's computer holds the keys for both. The relay changes that: one
small program (an AWS Lambda function) holds the keys, and each user
holds only a personal token. Losing a laptop then costs one token, not
the org's keys.

Everything runs in one Lambda function. There are no servers to manage,
nothing runs when nobody is dictating, and the pilot's usage fits far
inside the AWS free tier. Expect the AWS bill itself to be roughly
zero. The provider costs (OpenAI, Anthropic) do not change; they just
get billed through keys that live in AWS instead of on laptops.

## What you will create, in plain words

| Thing | What it is for |
|---|---|
| The account | A home for the function and the keys |
| An admin sign-in | So daily work never uses the all-powerful root login |
| Two secrets | The OpenAI and Anthropic keys, stored where only the relay can read them |
| A budget alarm | An email if the AWS bill ever exceeds a few dollars |
| Command-line access | So the deploy script can create and update the function |

You also put the two provider keys into the account (step 5), because
you are the person who can create them. The token list and the function
itself are **not** in this guide. A guided script (the setup wizard,
from ticket #22) creates those, because scripts do not mistype. Your
job is the account and the keys; the wizard's job is the rest.

## What you will NOT need

No servers (EC2), no databases, no VPC or networking, no domain names,
no API Gateway, no certificates. If a console page tries to sell you
one of these, close it.

## Step 1: Create the account

1. Go to https://aws.amazon.com and choose **Create an AWS Account**.
2. Use an org email address that more than one person can reach (a
   shared mailbox is ideal), not one person's personal inbox. This
   address becomes the **root user**, the account's master key.
3. AWS asks for a payment card and a phone number for verification.
   Choose the **Basic (free)** support plan.

## Step 2: Lock the root user away

The root login can do anything, including delete the account. Use it
for this step and then never again.

1. Sign in as root. Open **IAM** from the search bar.
2. On the IAM dashboard, follow the prompt to **enable MFA for the
   root user**. An authenticator app on a phone is fine.
3. Do not create access keys for the root user. If the console offers,
   decline.

## Step 3: Make the admin sign-in

This is the login for actual day-to-day work.

1. Still in IAM, choose **Users**, then **Create user**.
2. Name it `mirabel-voice-admin`. Allow console access; set a password.
3. Give it no policies yet. Step 7 grants exactly what the deploy
   needs. (The Lambda gets a smaller role still: the wizard scopes it
   to three named secrets and its own log group, nothing else.)
4. Enable MFA for this user too.
5. Sign out of root. From here on, always sign in as `mirabel-voice-admin`.

## Step 4: Set the region and keep it

Pick **us-east-2 (Ohio)** and select it in the region menu at the top
right of the console. Both providers' APIs are US-hosted, and one
region keeps everything findable.

Write the region down. Everything the wizard creates goes in this
region, and "my function disappeared" is almost always "wrong region
selected".

## Step 5: Put the provider keys into Secrets Manager

The relay reads its keys from AWS Secrets Manager. You create both
secrets by hand, so the keys go straight from the provider dashboards
into AWS and never sit anywhere in between.

First, create a fresh key at each provider. Do not reuse the existing
org keys: the old ones already sit on pilot laptops, and a key that was
never on a laptop needs no rotation later.

1. At https://platform.openai.com, create an API key named
   `mirabel-voice-relay`.
2. At https://console.anthropic.com, create an API key named
   `mirabel-voice-relay`.

Then store each one, making sure the region menu still shows the
region from step 4:

1. Search for **Secrets Manager** and choose **Store a new secret**.
2. Pick **Other type of secret**, then the **Plaintext** tab.
3. Delete the example JSON and paste the OpenAI key as the entire
   value. No quotes, no extra lines.
4. Name it exactly `mirabel-voice/openai`. Default encryption is fine;
   no rotation schedule. Save.
5. Repeat for the Anthropic key, named exactly `mirabel-voice/anthropic`.

The names matter: the relay looks these two up by name. The deploy
verifies both keys with a live test call, so a paste error is caught
before anyone dictates.

## Step 6: Budget alarm

1. Search for **Budgets** (under Billing and Cost Management).
2. Create a budget: monthly, fixed, **$10**.
3. Add an email alert at 50% and at 100%, to the shared mailbox.

The expected bill is around zero, so any alert from this is a signal
worth reading, not noise.

## Step 7: Permissions for the deploy user

The `mirabel-voice-admin` user needs rights to create the function,
its role, and the token list. There are two ways to grant them, and
the narrower one is the better one.

**Narrow (preferred).** In IAM, open the `mirabel-voice-admin` user,
choose **Add permissions** > **Create inline policy** > the **JSON**
tab. Paste the contents of `docs/deploy-policy.json` over what is in
the box, replacing `ACCOUNT_ID` with this account's number. Name it
`mirabel-voice-deploy`. That policy reaches one Lambda function, one
role, the `mirabel-voice/*` secrets, and that function's log group,
and nothing else in the account.

**Broad.** Attach the AWS managed policy **AdministratorAccess**
instead. Simpler, and appropriate only in an account that exists for
this one purpose.

Either way, this step needs root or an existing administrator. A user
cannot widen its own permissions - that is the point of them.

## Step 8: Command-line access for the deploy

The deploy script talks to AWS from a developer machine. It needs a
key pair for the `mirabel-voice-admin` user.

1. In IAM, open the `mirabel-voice-admin` user, choose **Security
   credentials**, then **Create access key**.
2. Pick **Command Line Interface (CLI)** as the use case.
3. You get two values: an access key ID and a secret access key. Treat
   the pair like a password. Hand it to the person running the wizard
   over a channel you trust, not email and not a ticket.
4. On the machine that will deploy, install the AWS CLI
   (https://aws.amazon.com/cli/) and run `aws configure`: paste the
   two values, set the region from step 4, leave the output format
   empty.

If your organization forbids long-lived access keys, use IAM Identity
Center instead: `aws configure sso`, then pass the profile through to
the scripts with `--profile`. Both work; the scripts do not care which
kind of credential they are handed.

## Step 9: Hand over

Tell the person running the wizard:

- The region (step 4)
- That the two secrets exist under the names in step 5
- That the deploy permissions are attached (step 7)
- That `aws configure` succeeded on the deploy machine (step 8)

That is the whole job. They run:

```
pip install -e .[dev]
python scripts/setup_relay.py
```

The wizard does the rest: the token list, the Lambda function, its
narrow permissions, the Function URL, and the first deploy. It finds
your two secrets by name and never asks anyone for a provider key. It
ends by printing the relay's address and one token per person.

Afterwards, every change to the relay is one command:

```
python scripts/deploy_relay.py
```

A second run updates what is there. It never creates a duplicate.

## Afterwards: what lives where

| Where | What |
|---|---|
| Secrets Manager | The two provider keys, and the token list |
| Lambda | The relay function and its URL |
| CloudWatch Logs | One usage line per dictation: who, how much, how long. Never any speech or text |
| Budgets | The $10 alarm |

## Questions you may have

**Can we use an existing org AWS account instead of a new one?**
Yes. Skip steps 1-3, pick a region, and make sure whoever runs the
wizard has rights to create Lambda functions, secrets, and IAM roles.
A dedicated account limits what a mistake can touch; an existing one
keeps billing in one place. Both work.

**Does this need to be done by a developer?**
No. Steps 1-8 are console clicking with no code, though step 5 needs
access to the org's OpenAI and Anthropic dashboards. The wizard step
needs only the deploy machine. For the pilot, that is Tommy.

**What happens if the card on the account expires?**
AWS emails the root address (the shared mailbox from step 1) well
before anything stops. The relay itself costs so little that even a
lapsed card takes months to matter.
