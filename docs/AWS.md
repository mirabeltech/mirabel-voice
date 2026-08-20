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
| A budget alarm | An email if the AWS bill ever exceeds a few dollars |
| Command-line access | So the deploy script can create and update the function |

The keys, the token list, and the function itself are **not** in this
guide. A guided script (the setup wizard, from ticket #22) creates
those for you, because scripts do not mistype. Your job is the account;
the wizard's job is everything inside it.

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
2. Name it `mirabel-admin`. Allow console access; set a password.
3. Attach the AWS managed policy **AdministratorAccess**. (The Lambda
   itself will get a far smaller role later. The wizard scopes it to
   exactly two secrets and its own logs. Admin here is for the human.)
4. Enable MFA for this user too.
5. Sign out of root. From here on, always sign in as `mirabel-admin`.

## Step 4: Set the region and keep it

Pick **us-east-1 (N. Virginia)** and select it in the region menu at
the top right of the console. Both providers' APIs are US-hosted, and
one region keeps everything findable.

Write the region down. Everything the wizard creates goes in this
region, and "my function disappeared" is almost always "wrong region
selected".

## Step 5: Budget alarm

1. Search for **Budgets** (under Billing and Cost Management).
2. Create a budget: monthly, fixed, **$10**.
3. Add an email alert at 50% and at 100%, to the shared mailbox.

The expected bill is around zero, so any alert from this is a signal
worth reading, not noise.

## Step 6: Command-line access for the deploy

The deploy script talks to AWS from a developer machine. It needs a
key pair for the `mirabel-admin` user.

1. In IAM, open the `mirabel-admin` user, choose **Security
   credentials**, then **Create access key**.
2. Pick **Command Line Interface (CLI)** as the use case.
3. You get two values: an access key ID and a secret access key. Treat
   the pair like a password. Hand it to the person running the wizard
   over a channel you trust, not email and not a ticket.
4. On the machine that will deploy, install the AWS CLI
   (https://aws.amazon.com/cli/) and run `aws configure`: paste the
   two values, set the region from step 4, leave the output format
   empty.

## Step 7: Hand over

Tell the person running the wizard:

- The region (step 4)
- That `aws configure` succeeded on the deploy machine (step 6)

They will also need the current **OpenAI** and **Anthropic** API keys
at wizard time, because the wizard puts them into AWS Secrets Manager.
The keys go straight from the provider dashboards into the wizard
prompt; they never need to be written down anywhere in between.

That is the whole account job. The wizard does the rest: the two key
secrets, the token list, the Lambda function, its narrow permissions,
and the first deploy.

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
No. Steps 1-6 are console clicking with no code. The wizard step needs
whoever has the provider keys and the deploy machine. For the pilot,
that is Tommy.

**What happens if the card on the account expires?**
AWS emails the root address (the shared mailbox from step 1) well
before anything stops. The relay itself costs so little that even a
lapsed card takes months to matter.
