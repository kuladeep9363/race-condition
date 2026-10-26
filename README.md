HackMart: Coupon Redemption Race-Condition CTF
A setup and replication guide for a deliberately vulnerable Flask +
SQLite web application. It explains the vulnerable behavior, how to
reproduce it in an authorized lab, and how to patch it.
> **Scope:** Run the vulnerable version only in a local lab or an
> environment where you have explicit permission to test. Do not expose
> the intentionally vulnerable build to the public internet.
1. What the challenge demonstrates
HackMart has a one-time coupon that adds ₹100 to a user's wallet.
Each account should be able to claim it once, and later attempts must
not add money.
The vulnerable implementation checks eligibility, waits briefly, and
then updates the wallet in a separate database operation. Concurrent
requests can all pass the initial check before any request marks the
coupon as claimed. This is a race condition, specifically a
time-of-check-to-time-of-use (TOCTOU) flaw.
Requests                     Correct result
---
One claim request            Wallet increases by ₹100
A later claim request        Rejected; no additional credit
Many simultaneous requests   Exactly one credit of ₹100
2. Technology and project layout
The app uses Python 3, Flask, SQLite, Jinja templates, and static
assets. A typical layout is:
``` text
hackmart/
├── app.py
├── requirements.txt
├── FLAG.txt
├── .gitignore
├── templates/
└── static/
    ├── css/
    ├── js/
    └── images/
```
The database is created at runtime. Use the database filename and
initialization logic present in your copy of `app.py` if they differ.
3. Setup
Windows (PowerShell)
Run these commands in the directory containing `app.py`:
``` powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```
If PowerShell blocks activation, use the environment's Python directly:
``` powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```
Linux / Kali
``` bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```
Open the local URL printed by Flask. With the default development port,
it is usually:
``` text
http://127.0.0.1:5000/
```
For testing from another machine on a private lab network, configure
Flask to listen on the appropriate interface and use the server's
reachable private IP. Do not expose this vulnerable build to an
untrusted network.
Create a test account
Open the registration page and register a test account.
Log in and open the coupon page.
Confirm the coupon is available and record the wallet balance.
Use a fresh account for each clean test, or reset the account's
coupon status and wallet using the lab's database reset procedure.
4. Vulnerable implementation
The route in the vulnerable version looks like this:
``` python
@app.post("/claim")
@login_required
def claim_coupon():
    user_id = current_user()["id"]

    # Vulnerable: eligibility check is separate from the credit operation.
    with connect_db() as db:
        row = db.execute(
            "SELECT coupon_claimed FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

    if not row or row["coupon_claimed"]:
        flash(
            "Coupon already claimed. Each account can claim it once.",
            "error"
        )
        return redirect(url_for("coupon"))

    # Makes the race window easier to reproduce in the lab.
    time.sleep(0.35)

    with connect_db() as db:
        db.execute(
            """
            UPDATE users
            SET wallet = wallet + 100,
                coupon_claimed = 1
            WHERE id = ?
            """,
            (user_id,)
        )
        db.commit()

    flash("Coupon redeemed: ₹100 added to your wallet.", "success")
    return redirect(url_for("coupon"))
```
Why it is vulnerable
The `SELECT` and `UPDATE` use separate database connections and are not
one atomic operation. A possible timeline is:
Request A reads `coupon_claimed = 0`.
Request B reads `coupon_claimed = 0`.
Both requests pass the eligibility check.
Request A credits ₹100 and sets the flag.
Request B also credits ₹100 and sets the flag.
The final value `coupon_claimed = 1` does not prove the coupon was
credited only once. The wallet increment may already have happened more
than once.
The `time.sleep()` is not the root cause. It widens the race window so
the behavior is easier to observe in the challenge.
5. Intended exploit (authorized lab only)
The endpoint accepts `POST` requests and relies on the authenticated
session cookie. This sends ten requests concurrently. Replace the cookie
placeholder with a valid session cookie from your own test account and
use your lab URL.
``` bash
seq 10 | xargs -P10 -I{} curl -s \
  -X POST \
  -b "hackmart_session=YOUR_VALID_SESSION_COOKIE" \
  -o /dev/null \
  -w "request {}: HTTP %{http_code}\n" \
  http://127.0.0.1:5000/claim
```
Notes:
The cookie name above is `hackmart_session`, based on the updated
app's custom authentication cookie. If your copy uses a different
name, use the actual cookie name and value.
If testing from a separate lab machine, replace `127.0.0.1` with the
lab server's reachable private IP and port.
A redirect response alone does not prove exploitation succeeded.
Check the wallet balance or the relevant database row.
Use an account whose coupon has not yet been claimed.
Verify the result
Record the wallet balance before the test. After the requests finish,
inspect the balance in the app or database. In the vulnerable version, a
successful race may produce an increase greater than ₹100. The exact
number of duplicate credits depends on request scheduling, so the
maximum is not guaranteed on every run.
6. Patch the race condition
Replace the vulnerable route with this version. It uses the helper names
from the supplied route (`connect_db`, `current_user`, `login_required`,
and `coupon`) and a conditional update inside a SQLite write
transaction.
``` python
@app.post("/claim")
@login_required
def claim_coupon():
    user_id = current_user()["id"]

    with connect_db() as db:
        # Acquire SQLite's write transaction before performing the claim.
        db.execute("BEGIN IMMEDIATE")

        result = db.execute(
            """
            UPDATE users
            SET wallet = wallet + 100,
                coupon_claimed = 1
            WHERE id = ?
              AND coupon_claimed = 0
            """,
            (user_id,)
        )

        if result.rowcount == 1:
            db.commit()
            success = True
        else:
            db.rollback()
            success = False

    if success:
        flash("Coupon redeemed: ₹100 added to your wallet.", "success")
    else:
        flash(
            "Coupon already claimed. Each account can claim it once.",
            "error"
        )

    return redirect(url_for("coupon"))
```
Why the patch works
`BEGIN IMMEDIATE`: starts a SQLite write transaction before the
claim update. Competing writers wait rather than independently
passing a stale eligibility check.
Conditional update: `AND coupon_claimed = 0` means the wallet is
credited only if the coupon is still unclaimed when the update
executes.
`rowcount`: one updated row indicates success. Zero rows means
the coupon was already claimed or the user row does not exist.
Single transaction: the wallet increment and setting
`coupon_claimed = 1` happen together.
The conditional update enforces the business rule; the transaction
serializes competing SQLite writers. Keep both.
Database timeout consideration
If `connect_db()` configures a very short SQLite busy timeout,
concurrent requests may encounter `database is locked`. Set a reasonable
timeout in the connection helper, for example:
``` python
sqlite3.connect(DATABASE, timeout=10)
```
Adapt `DATABASE` to the database path variable in your app. A timeout
helps requests wait for a lock; it does not replace atomic claim logic.
7. Retest after patching
Restart Flask so the updated code is loaded.
Use a fresh account with an unclaimed coupon.
Record the initial wallet balance.
Run the same concurrent request command.
Inspect the final wallet and `coupon_claimed` value.
Expected result:
`coupon_claimed` is `1`.
The wallet increases by exactly ₹100.
Only one request claims the coupon successfully.
Repeating the request does not add more money.
Test sequential and concurrent requests. Do not rely only on HTTP status
codes, because the route redirects after both success and failure.
8. Troubleshooting
The command redirects but the balance does not change
Confirm the session cookie is valid and belongs to the account being
inspected.
Confirm the cookie name matches the app (`hackmart_session` in the
updated version).
Confirm the account has not already claimed the coupon.
Inspect the Flask logs and the wallet row in SQLite.
The vulnerable version does not reproduce every time
Race conditions depend on request timing. Use a fresh account and
confirm the vulnerable version still has the delay between the
eligibility check and update. A successful exploit is not guaranteed on
every run.
The patched version reports a database lock error
Review the timeout configured by `connect_db()` and ensure all writes
use normal SQLite transactions. Do not remove the conditional update to
work around lock errors.
Changes have no effect
Ensure the Flask process was restarted and that you edited the `app.py`
actually being executed. Check the current working directory if multiple
copies of the project exist.
9. Security lesson
A check followed by a later write is unsafe when multiple requests can
act on the same state concurrently. Enforce one-time business rules in
the database operation itself, and group related state changes in a
transaction. For more complex redemption systems, a uniqueness
constraint or dedicated redemption record can also enforce one
redemption per user and coupon.
10. Before sharing or deploying
Keep the vulnerable version confined to the CTF lab.
Do not use real user data or real payment functionality in this
challenge.
Keep the patched version as the production-safe reference.
Make clear to participants that the challenge is intentionally
vulnerable and authorized for testing.
