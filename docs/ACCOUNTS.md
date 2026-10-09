# Accounts and security

Sign-up, sign-in, the Account area, two-factor, the audit log and the
superuser overrides. Everything lives in `accounts/`. The requirements are
in `prd/account-security.md` and its dated amendments, and the build order
is in `plans/account-security.md`.

## The deep module

`accounts/security.py` is the codebase's fourth deliberate deep module.
Every rule that decides whether an account is safe lives there: TOTP
secrets and code checks, recovery codes, the sign-in cooldown, recording
events, alert emails, signed email links, the device list and the admin
overrides. Views, forms, the admin, middleware, signals and management
commands call into it and hold no security logic of their own. Keep it
that way: a new security behaviour is a new function there, with a
docstring and type hints, and a thin caller.

## The audit log is the source of truth

`SecurityEvent` records every security-relevant change. Three features
count rows from it instead of keeping a column of their own:

- the **cooldown**, which counts recent failures and pauses
- the Account page's **activity card** (the owner's last 10 events)
- **"password last changed"** (`User.password_last_changed`)

So anything security-relevant must go through `security.record_event`.
If you skip it, the cooldown, the activity card and the admin's history
all miss the change.

- `user` and `actor` are `SET_NULL`, and `username` keeps a snapshot, so
  an account's history survives its deletion.
- An admin override is the matching event type with the admin as
  `actor`. The owner sees it as "by ThoughtTronix support", never with
  the admin's name. `actor=None` means the server did it (`reset_2fa`).
- The IP is `REMOTE_ADDR` only. Forwarded headers are spoofable without a
  known proxy.
- **Never store** passwords, codes, tokens, secrets or the identifier
  typed into a failed sign-in. People type passwords into the username
  box.
- The `SecurityEvent` admin is read-only for everyone and visible to
  superusers only.

## Identity

- Usernames and emails are each unique case-insensitively, through
  functional constraints on `Lower(...)`. Blank emails are exempt because
  older accounts have `""`. Emails are stored as typed.
- Usernames can't contain `@`, so `UsernameOrEmailBackend` can match
  either field without ambiguity. It replaces `ModelBackend`, refuses
  inactive users, and records failed sign-ins itself. A cooldown refusal
  must not be recorded, and only the backend can tell the two apart.
- **Locked** means `is_active = False`. There is no separate flag.
- `User.session_key` is mixed into the session auth hash.
  `rotate_session_key()` signs out every other session without changing
  the password.

## Sign-in

- **Two steps** for two-factor users. Step 1 stores only "user X passed
  the password at time T" in the session, and the user is **not** signed
  in until step 2 accepts an authenticator or recovery code. The pending
  state lasts 5 minutes. `/admin/login/` redirects to the store's sign-in
  page, so no sign-in skips step 2.
- **The cooldown.** Five failures within 15 minutes start a pause of 15,
  then 30, then 60 minutes. Wrong passwords and wrong codes share one
  total, and that includes wrong answers on re-authentication forms.
  Attempts refused during a pause are neither checked nor recorded. A
  successful sign-in or a cleared cooldown resets the ladder.
- **Every refusal shows the same message.** The "attempts left" line
  under it comes from this browser's session, not the account's history,
  so it never reveals whether an account exists.
- `user_logged_in` (in `signals.py`) records the sign-in and creates the
  `UserSession` row behind the Account page's device list.
  `UserSessionMiddleware` signs a browser out once its row is gone.
- `TwoFactorRequiredMiddleware` sends a superuser without two-factor to
  setup from every page, `/admin/` included. Only setup, sign-out and
  static/media files are exempt.

## Proving it's you

Every sensitive form subclasses `ReauthenticationForm`:

- **No two-factor:** the form asks for the current password.
- **Two-factor on:** the field becomes "Current password or authenticator
  code".
- **"Ask for a code on security changes" chosen:** the form asks for the
  password *and* a code.
- **Turning two-factor off:** always asks for both.

Re-authentication accepts authenticator codes but not recovery codes. A
code is checked last, so a typo elsewhere on the form doesn't spend it.
Every code works once, because each device stores the last time step it
accepted. Checkout uses the same `AuthenticatorCodeMixin` when the owner
asks to be asked there.

## Email

All mail goes to the console. `security.send_alert` sends every alert,
ends "Wasn't you? Contact support." and silently skips accounts with no
email. Sign-ins and failed attempts never send mail. The one exception is
the start of a pause, which emails the owner once.

Verification and email-change links are signed tokens (no table) that
expire after 24 hours. They die once the account's email changes. **A
token link never changes anything on GET.** It opens a page whose
"Confirm" button POSTs, so mail scanners can't confirm anything. A
password reset uses Django's own views and tokens, with
`PASSWORD_RESET_TIMEOUT = 3600`.

## Admin overrides

Superusers only. Every override goes through a `security` function that
records the event with the admin as actor and emails the owner.

- **List actions:** mark email verified, reset two-factor, clear
  cooldown, lock, unlock and send reset link.
- **Change-page edits:** username, email, "Active" and set password.
- **The guardrail:** `security.overridable` skips the acting admin and
  every superuser. On a superuser's change page, username, email,
  "Active" and password are read-only, and the set-password URL answers
  403. Superusers change their own accounts through the Account area.
- **Staff who aren't superusers** get nothing new in the admin.

## Break-glass

```bash
uv run python manage.py reset_2fa <username>
```

This deletes the account's two-factor device and recovery codes, records
a 2FA-reset event with no actor, and emails the owner. It is the one
override that works on a superuser, so it recovers an admin who has lost
both their phone and their recovery codes. Their next sign-in takes the
password alone and lands on setup. An unknown username fails with an
error, and an account without two-factor is left alone. Use Django's own
`changepassword` for a lost password.

## Settings

Read from `.env` with development defaults, and listed in `.env.example`:

| Setting | Default | Change it when |
|---|---|---|
| `SESSION_COOKIE_SECURE` | `False` | serving over HTTPS: set `True` |
| `CSRF_COOKIE_SECURE` | `False` | serving over HTTPS: set `True` |
| `SESSION_COOKIE_AGE` | `1209600` (two weeks) | sign-ins should expire sooner |

`SESSION_COOKIE_AGE` also decides when an idle device drops off the
Account page's device list.

## Seed and the committed database

`seed` enrols **nobody** in two-factor and deletes every device and
recovery code, not just its own accounts'. The seeded `admin` is
therefore walked through two-factor setup at first sign-in after every
`seed`. `admin` and `employee` are seeded verified and `customer`
unverified.

TOTP secrets are stored in plain text, and `db.sqlite3` is committed.
**Run `seed` before committing `db.sqlite3`**, so no real secret reaches
git history.

## Tests

One file per phase, `accounts/test_*.py`. Make TOTP codes with
`pyotp.TOTP(device.secret)` against a fixed clock, and never sleep. The
`enrol_two_factor` fixture in `conftest.py` turns two-factor on, and any
superuser a test signs in as needs it.
