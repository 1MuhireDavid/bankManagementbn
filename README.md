# Bank management wallet API

Django 5.2 LTS, Django REST framework and MySQL 8.0+. Deposits are simulated;
this project does not initiate payments through a bank or payment provider.

The project separates account concerns from money concerns:

- `users/` owns registration, login, Bearer authentication, account permissions,
  the admin-only user/wallet list, and the user-to-wallet creation signal.
- `wallets/` owns wallet and transaction models, balance-changing services,
  wallet endpoints, constraints, migrations, and transaction history.
- Django's built-in user model remains the source of identity and password storage;
  `Wallet.owner` links to it with a one-to-one relationship.

## Local setup

Activate the virtual environment, install dependencies, and copy `.env.example`
to `.env` if you do not already have one. Set `DB_PASSWORD`, `DB_HOST` and
`DB_PORT` for the `bankmgt` database. The default database user is `springstudent`.

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check --database default
python manage.py runserver
```

Register and log in through the API as described below. The old
`prepare_wallet_user` command is no longer needed and has been removed.
Creating a user through registration, Django admin, `create_user()` or
`createsuperuser` automatically creates their zero-balance wallet. Migration
`0003` also links users that existed before this feature, preserving existing wallets.
As with Django signals generally, `bulk_create()` and raw fixture loading do not
run this linking flow; use normal user creation when adding accounts.

Create your administrator with `python manage.py createsuperuser`. Public
registration always creates ordinary users and cannot grant staff privileges.
Wallet balances and transaction records are read-only in admin; use the service
to change balances. Keep tokens private and use HTTPS outside local development.

## Swagger UI: test in your browser

Start the server with `python manage.py runserver`, then open
<http://127.0.0.1:8000/api/docs/>. The OpenAPI schema is at `/api/schema/`.
Swagger's assets are served locally, so the page does not require a CDN.

1. Expand POST `/api/users/register/` and register a username, email and strong
   password. The 201 response includes your user ID, wallet ID and zero balance;
   passwords are never returned.
2. Expand POST `/api/users/login/`, submit that username and password, and copy
   the `token` from the response.
3. Click **Authorize** in Swagger. In **bearerAuth**, paste only the returned token,
   then authorize and close the dialog. Swagger adds the `Bearer ` prefix.
4. Expand an endpoint, click **Try it out**, enter the JSON body if needed, and
   click **Execute**. Swagger displays the response and status code.
5. Start with GET `/api/wallet/`, then deposit `5000.00`, withdraw `2000.00` and
   inspect history. The POST endpoints include example bodies.

Example registration body (choose your own password):

```json
{"username": "alice", "email": "alice@example.com", "password": "Choose-a-strong-password!42"}
```

Example login body:

```json
{"username": "alice", "password": "Choose-a-strong-password!42"}
```

Registration applies Django's configured password validators and stores a hash
using `create_user()`. Username uniqueness is enforced; email is required and
validated but is not a unique login identifier. User and wallet creation are
atomic. Registration is limited to 10 requests/minute and login to 20/minute per
client IP using DRF throttling. For multiple application workers, configure a
shared Django cache to share these throttle counters.

For the testing list, register at least five accounts, log in as your administrator,
authorize their token, then GET `/api/users/wallet-list/`. Each page contains up to
20 accounts with `id`, `username`, `wallet_id` and `balance`. The list reflects
existing users; a GET request never creates fake accounts to fill a page.
Normal users get 403 and anonymous users get 401. To test a selected user's
balance changes, log in as that user and replace the token in Swagger Authorize.
Submitting somebody else's owner or wallet ID never redirects an operation.

Use a new reference for each new operation. Reuse the same reference and details
only to test an exact retry. Refreshing the page clears the entered API token.
The documentation is public; all wallet operations still require authentication.
Only canonical wallet routes appear in the schema alongside the account endpoints.

Validate the generated schema with:

```powershell
python manage.py spectacular --validate --fail-on-warn --file schema.yml
```

## Endpoints and manual checkpoints

Add `Authorization: Bearer YOUR_TOKEN` to protected requests. POST requests use
`Content-Type: application/json`. Decimal amounts are returned as strings.

| Method | URL | Purpose |
| --- | --- | --- |
| POST | `/api/users/register/` | Public registration and automatic wallet creation |
| POST | `/api/users/login/` | Public login to obtain a token |
| GET | `/api/users/wallet-list/` | Admin-only user/wallet listing, 20 accounts per page |
| GET | `/api/wallet/` | Authenticated user's balance and creation date |
| POST | `/api/wallet/deposit/` | Simulated deposit |
| POST | `/api/wallet/withdraw/` | Withdrawal |
| GET | `/api/wallet/transactions/?page=1` | Newest transactions first, 20 per page |

The original `/api/wallets/` routes remain available as aliases.
Users and wallets are always selected from the authenticated user, never an
owner or wallet ID supplied by the client. A user without a wallet gets 404.
Missing or invalid tokens get 401. The API uses Bearer authentication exclusively;
Django admin continues to use its normal session login. Existing database tokens
remain valid with the new header prefix. These are opaque DRF tokens, not JWTs.

1. GET the wallet: a new wallet returns `"balance": "0.00"`.
2. POST this JSON to the deposit endpoint:

   ```json
   {"amount": "5000.00", "reference": "demo-deposit-001"}
   ```

   Response (HTTP 200):

   ```json
   {"reference": "demo-deposit-001", "transaction_type": "deposit", "amount": "5000.00", "new_balance": "5000.00"}
   ```

3. Repeat the same request: the same response is returned and only one record exists.
4. Withdraw `2000.00` with reference `demo-withdraw-001`: balance becomes `3000.00`.
5. Attempt to withdraw `4000.00` with a fresh reference: HTTP 400, balance stays
   `3000.00`, and no transaction is recorded.
6. Repeat the successful withdrawal: balance stays `3000.00`.
7. Fetch history: two records, withdrawal first. The response includes `count`,
   `next`, `previous` and `results`. Each result has type, amount, reference and date.
8. Register a second user and use their login token: their wallet is zero and history empty.
9. Remove the token: requests return 401.

Amounts are required, positive, limited to two decimal places and eight integer
digits. References are required, trimmed, nonblank, limited to 100 characters
and globally unique. Invalid input returns 400 before any balance changes.
Reusing a reference with another wallet, type or amount returns 409. Exact retries
return the original resulting balance, even if later operations changed the wallet.
References use the database's collation when checking uniqueness.

## Transaction safety

`wallets/services.py` wraps balance updates and history inserts in
`transaction.atomic()` and locks the wallet using `select_for_update()`.
The unique reference constraint also protects requests racing across different
wallets. An insert failure rolls back the balance update. Database constraints
prevent negative balances, nonpositive amounts, blank references and invalid
transaction types. The balance cannot exceed `99999999.99`.

Migration `0002` converts legacy Credit/Debit labels to deposit/withdrawal,
assigns references to old records that have none and reconstructs balance
snapshots. Existing duplicate references or inconsistent negative snapshots
require manual reconciliation; migration does not silently discard history.

## Verification and table inspection

The test database uses the configured MySQL server, including real row locks.
The database account must be allowed to create and drop `test_bankmgt`.

```powershell
python manage.py test users wallets --noinput
python manage.py makemigrations --check --dry-run
python manage.py showmigrations
python manage.py dbshell
```

In the MySQL shell:

```sql
SHOW CREATE TABLE wallets_wallet;
SHOW CREATE TABLE wallets_wallettransaction;
SELECT id, owner_id, balance FROM wallets_wallet;
SELECT wallet_id, transaction_type, amount, reference, balance_after
FROM wallets_wallettransaction ORDER BY created_at DESC, id DESC;
```

The `users` tests cover registration, hashing and password validation, signal-based
wallet creation, registration rollback, login, admin listing with at least five
registered users, existing-user linking, and authentication. The `wallets` tests
cover user isolation, validation, duplicate references, pagination, balance limits,
database constraints, atomic rollback
and concurrent deposits, withdrawals and reference collisions.
