"""
Walking skeleton, step 1: prove we can authenticate to Stripe and
reach our test connected account.

Purpose: if auth or the account ID is wrong, every downstream step
(Customer, SetupIntent, PaymentIntent) will fail with confusing
errors. Catch the foundation problems here, in isolation.
"""

import os
from dotenv import load_dotenv   # reads .env file into os.environ
import stripe

# Load .env into the process environment.
# Must happen before any os.environ reads below.
load_dotenv()

# Configure the Stripe SDK globally.
# Every stripe.* call in this process will use this key.
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Fail loudly if the key is missing — silent failures are worse.
# (Renamed from TEST_PLANNER_ACCOUNT_ID on 2026-07-16: the live
# connected account must not live in a variable named "test".)
planner_account_id = os.environ["PLANNER_ACCOUNT_ID"]

# Single API call: retrieve the connected account by ID.
# If this succeeds, auth + connectivity are confirmed.
account = stripe.Account.retrieve(planner_account_id)

print(f"Account ID:       {account.id}")
print(f"Type:             {account.type}")
print(f"Charges enabled:  {account.charges_enabled}")
print(f"Payouts enabled:  {account.payouts_enabled}")
print(f"Country:          {account.country}")