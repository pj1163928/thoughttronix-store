# Plan: Account Management and Security

> Source PRD: `prd/account-security.md` (builds on `prd/core-platform.md`).
> The PRD owns the requirements; this plan owns the sequence. Where a
> phase says "per the PRD", the PRD's wording is authoritative.

## Architectural decisions

Durable decisions that apply across all phases:

- **Owning app**: `accounts`, and no new app. Everything lives under the
  existing `accounts` namespace at `/accounts/`.
- **Deep module**: `accounts/security.py` is the fourth deliberate deep
  module, with docstrings and type hints on every public function. It owns
  TOTP generation and checking (±1 step drift, replay protection),
  recovery codes, the sign-in throttle, recording `SecurityEvent`s and
  sending alert emails. Views, forms, the admin, middleware and management
  commands call into it and contain no security logic of their own.
- **Dependencies**: `pyotp` (TOTP) and `segno` (QR as inline SVG). No
  `django-otp`, `django-allauth` or `django-axes`.
- **Views**: one class-based view and one small form per page, following
  `PasswordChangeView`. No multi-form pages, **no HTMX** (the HTMX
  inventory is unchanged), and outcomes are reported with
  `django.contrib.messages`. Token links never change anything on GET:
  they open a page whose "Confirm" button POSTs.
- **URLs** (all `accounts:`):

  | Page | Path | Name |
  |---|---|---|
  | Account hub | `/accounts/` | `account` |
  | Change username | `/accounts/username/` | `change_username` |
  | Change email | `/accounts/email/` | `change_email` |
  | Confirm email change (token, no sign-in) | `/accounts/email/confirm/<token>/` | `confirm_email_change` |
  | Resend verification (POST) | `/accounts/email/verify/` | `send_verification` |
  | Verify email (token, no sign-in) | `/accounts/email/verify/<token>/` | `verify_email` |
  | Change password | `/accounts/password/` | `password_change` |
  | Reset: request | `/accounts/password/reset/` | `password_reset` |
  | Reset: sent | `/accounts/password/reset/sent/` | `password_reset_done` |
  | Reset: set new | `/accounts/password/reset/<uidb64>/<token>/` | `password_reset_confirm` |
  | Reset: done | `/accounts/password/reset/complete/` | `password_reset_complete` |
  | 2FA setup | `/accounts/2fa/setup/` | `two_factor_setup` |
  | 2FA off | `/accounts/2fa/disable/` | `two_factor_disable` |
  | Regenerate recovery codes | `/accounts/2fa/recovery-codes/` | `recovery_codes` |
  | Sign-in step 2 | `/accounts/login/verify/` | `login_verify` |
  | Sign out other devices (POST) | `/accounts/sessions/sign-out-others/` | `sign_out_others` |

  Existing sign-up, sign-in, sign-out and address-book URLs are unchanged.
- **Models**:
  - `User` gains a nullable email-verified timestamp and a session key
    field mixed into the session auth hash. Rotating it signs out every
    other session.
  - `User` constraints: a case-insensitive functional unique constraint
    on email that excludes blank emails, a case-insensitive functional
    unique constraint on username, and a validator that rejects `@` in
    usernames.
  - Two-factor device (one-to-one with `User`): the secret (stored
    plain), a confirmed-at timestamp (null while pending) and the last
    used time step. Two-factor is "on" when a confirmed device exists.
  - Recovery code (ten per user, FK `User`): a SHA-256 hash and a used-at
    timestamp. Regenerating replaces the whole set.
  - `SecurityEvent`: `user` and `actor` FKs to `User`, both `SET_NULL`,
    plus a username snapshot, event type (`TextChoices`), timestamp, IP
    (`REMOTE_ADDR` only) and a small JSON `details` field. It never stores
    passwords, codes, tokens or secrets. An admin override is the
    matching event type with the admin as actor.
  - No extra columns for "password last changed" (derived from events) or
    the cooldown (counted from events).
- **Authentication**: a custom username-or-email backend replaces
  `ModelBackend` and keeps its permission behaviour and its refusal of
  inactive users. Locked means `is_active = False`. Sign-in is two steps
  for two-factor users, and the user is **not** signed in between them.
- **Authorization**: account pages require sign-in, except the token and
  reset pages. Overrides and the `SecurityEvent` admin are superuser-only.
  Hiding the "User security" link is cosmetic, because the admin's own
  permission checks are the gate. Superusers can't apply overrides to
  themselves or to other superusers.
- **Email**: console backend only. Every alert goes through one helper in
  `accounts/security.py`, which silently skips accounts with no email.
  Sign-ins and failures never send mail.
- **Settings**: `AUTHENTICATION_BACKENDS` lists the custom backend.
  `PASSWORD_RESET_TIMEOUT = 3600`. `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE` and `SESSION_COOKIE_AGE` are read from `.env` with
  development defaults.
- **Testing**: pytest with plain fixtures per `docs/TESTING.md`. TOTP codes
  are generated with `pyotp` from the test device's secret against a
  fixed clock, with no sleeping.

---

## Phase 1: Audit log tracer

**User stories**: 42, 43

### What to build

The `SecurityEvent` model and the `accounts/security.py` function that
records one, wired to the two events that already happen today: signing
up, and signing in (succeeded and failed). Each event captures the IP
from `REMOTE_ADDR` and a username snapshot. A read-only `SecurityEvent`
admin is visible to superusers only and filterable by event type, date
and actor, searchable by username snapshot. The seed gives every seeded
user a sign-up event.

### Acceptance criteria

- [x] Signing up records a sign-up event for the new user with their IP.
- [x] Successful and failed sign-ins each record their event type.
- [x] Deleting a user leaves their events in place with `user` null and
      the username snapshot intact.
- [x] The `SecurityEvent` admin allows no add, change or delete for
      anyone, superusers included.
- [x] Staff who aren't superusers can't see the `SecurityEvent` admin.
- [x] `seed` runs twice cleanly, and every seeded user has a sign-up
      event.
- [x] Every public function in `accounts/security.py` has a docstring and
      type hints.

---

## Phase 2: Email at sign-up and identity rules

**User stories**: 1, 2, 3

### What to build

Sign-up asks for an email address alongside the username and password.
Emails are unique case-insensitively, ignoring blank emails from older
accounts. Usernames are unique case-insensitively and can't contain `@`.
The migration first scans existing rows and fails with a message that
names any case-insensitive duplicate emails or usernames. It never merges
or renames them. `SignupForm`'s "No email" docstring is updated.

### Acceptance criteria

- [x] Sign-up without an email is refused with a field error.
- [x] Sign-up with `Casey@Example.com` is refused when `casey@example.com`
      exists, and the email is stored as entered.
- [x] Sign-up with a username containing `@`, or one differing from an
      existing username only by case, is refused.
- [x] Two existing accounts with blank emails don't violate the
      constraint.
- [x] The migration's duplicate check fails with the offending values
      named, and passes on clean data.

---

## Phase 3: Username-or-email sign-in

**User stories**: 5

### What to build

A custom authentication backend matches the identifier case-insensitively
against username or email. It replaces `ModelBackend` in settings and
keeps its permission behaviour and its refusal of inactive users. The
sign-in field is relabelled "Username or email".

### Acceptance criteria

- [ ] A user can sign in with their username or their email, in any
      capitalisation.
- [ ] An inactive (locked) user is refused with the same message as a
      wrong password.
- [ ] Staff and superuser permission checks behave exactly as before.
- [ ] The sign-in page labels the field "Username or email".

---

## Phase 4: Sign-in cooldown

**User stories**: 16, 17, 38

### What to build

The throttle lives in `accounts/security.py` and counts failures from
`SecurityEvent`. Five failures on one account within 15 minutes refuse
further attempts until the oldest failure ages out. Failures from before
the most recent successful sign-in or "cooldown cleared" event don't
count. Attempts refused during a cooldown aren't checked or recorded. A
wrong password, an unknown account and a cooldown all show the PRD's one
identical message. Failed sign-ins for unknown identifiers are logged with
no user and no identifier, only the IP. No failure ever sends mail.

### Acceptance criteria

- [ ] After five wrong passwords in 15 minutes, the correct password is
      refused.
- [ ] The cooldown ends on its own once the oldest failure is more than
      15 minutes old (tested with a fixed clock).
- [ ] Attempts made during a cooldown don't extend it.
- [ ] A successful sign-in resets the count.
- [ ] Wrong password, unknown account and cooldown produce byte-identical
      messages.
- [ ] An unknown-identifier failure is stored with null user, no
      identifier anywhere in the row, and the IP.
- [ ] No email is sent for any failed sign-in.

---

## Phase 5: Account hub and navigation

**User stories**: 18, 19, 20, 22, 23

### What to build

The Account page at `/accounts/` shows a Profile card (username, email,
verified badge), a Password card ("last changed …" from the newest
password-changed or reset-completed event, otherwise "Never changed"), an
Addresses card linking to the unchanged address book, and a Recent
security activity card with the user's own last 10 events: what happened,
when and from which IP. An event with another person as actor reads "by
ThoughtTronix support" and never names the admin. Accounts with no email
see a banner asking them to add one. The navbar's "Addresses" link becomes
"Account". Cards for later features appear in their phases.

### Acceptance criteria

- [ ] Anonymous visitors are redirected to sign in.
- [ ] The navbar shows "Account" linking to `accounts:account` and no
      longer shows "Addresses".
- [ ] The activity card shows only the signed-in user's events, newest
      first, capped at 10.
- [ ] An event whose actor is an admin reads "by ThoughtTronix support"
      and never contains the admin's username.
- [ ] The Password card reads "Never changed" when no qualifying event
      exists.
- [ ] An account with a blank email sees the add-email banner.

---

## Phase 6: Change password and sign out other devices

**User stories**: 24, 31, 36, 37 (password changed)

### What to build

This phase builds three shared pieces that later phases reuse. The
session key field on `User` is mixed into the session auth hash. The
"Current password" re-authentication field is wired into the cooldown, so
wrong answers count toward it. The alert-email helper says what happened
and when, ends "Wasn't you? Contact support." and skips email-less
accounts. Using them, the change-password page keeps this session signed
in, signs out every other session, records the event and sends an alert.
The "Sign out of all other devices" button on the hub takes the current
password, rotates the session key and records its event.

### Acceptance criteria

- [ ] Changing the password requires the current password, keeps the
      current session signed in and invalidates a second session.
- [ ] "Sign out of all other devices" invalidates a second session
      without changing the password, and records its event.
- [ ] A wrong current password on either form counts toward the sign-in
      cooldown.
- [ ] A password change sends one alert email with the required wording.
      An account with no email gets none and no error.
- [ ] The hub's Password card shows the new "last changed" time.

---

## Phase 7: Change username

**User stories**: 27, 37 (username changed)

### What to build

A change-username page guarded by the current password. It applies the
same rules as sign-up: case-insensitive uniqueness and no `@`. It records
a username-changed event with the old and new usernames in `details` and
sends an alert.

### Acceptance criteria

- [ ] A valid rename takes effect immediately, and the user stays signed
      in.
- [ ] Renames that collide case-insensitively or contain `@` are refused.
- [ ] A wrong current password refuses the change and counts toward the
      cooldown.
- [ ] The event's `details` hold the old and new usernames, and an alert
      is sent.

---

## Phase 8: Email verification

**User stories**: 4, 21

### What to build

Verification links use a signed, timestamped token that carries the user
ID and email, expires after 24 hours and needs no new table. Sign-up sends
one, and the account works immediately. The hub shows "Email not verified
— resend link" for unverified emails, which POSTs to `send_verification`.
The link opens a page with a "Confirm" button that POSTs, works without
signing in, sets the verified timestamp and records an email-verified
event. The seed marks `admin` and `employee` verified and `customer`
unverified.

### Acceptance criteria

- [x] Sign-up prints a verification email to the console, and the new
      user can sign in immediately.
- [x] GET on a verification link changes nothing. POST verifies.
- [x] A link older than 24 hours, or for an email the account no longer
      has, is refused.
- [x] The hub shows the resend prompt only for unverified emails, and the
      verified badge otherwise.
- [x] After `seed`, `customer` is unverified and `admin`/`employee` are
      verified.

---

## Phase 9: Change email by confirmation link

**User stories**: 28, 29, 30

### What to build

The change-email page takes the new address and the current password, and
the email doesn't change yet. A token carrying the user ID, new address
and current address is mailed to the new address and expires after 24
hours. Confirming it (GET shows a button, POST acts) re-checks uniqueness,
switches the email, marks it verified, records the event and sends a
notice to the old address. The token is refused if the account's current
email no longer matches the one it carries.

### Acceptance criteria

- [x] Before confirmation, the old email stays in effect for sign-in and
      reset.
- [x] Confirmation switches the email, marks it verified and emails the
      old address.
- [x] Confirmation is refused if the new address has been taken in the
      meantime.
- [x] Confirmation is refused after 24 hours, or if the email changed
      after the token was issued.
- [x] GET on the confirmation link changes nothing.

---

## Phase 10: Password reset

**User stories**: 6, 7, 8, 9

### What to build

Django's built-in reset views, restyled and mounted at the namespaced
URLs, each with an explicit namespaced success URL and email template.
`PASSWORD_RESET_TIMEOUT` is one hour. The matched email doesn't need to be
verified. "Reset requested" is logged only when an account matched. A
completed reset records its event, sends an alert and doesn't sign the
user in. The sign-in page links to the reset page.

### Acceptance criteria

- [x] The request page shows the same response and redirect for a known
      and an unknown email.
- [x] A reset link works once, expires after an hour (fixed clock), and
      dies if the password changes first.
- [x] Completing a reset invalidates every existing session and leaves the
      user signed out.
- [x] "Reset requested" is logged only for a matched account. "Reset
      completed" is logged and alerted.
- [x] No reset view redirects to an un-namespaced URL name.

---

## Phase 11: Two-factor enrolment

**User stories**: 32, 33, 37 (2FA turned on)

### What to build

Adds the two-factor device and recovery code models and the
`accounts/security.py` functions for secret generation, provisioning URIs
and code checking with ±1 step drift. The setup page shows a `segno` QR
code as inline SVG and the typed setup key while setup is unconfirmed. It
switches two-factor on only after a working code is entered. No
re-authentication is needed. On success, 10 recovery codes are shown
once, stored only as hashes. The hub gains a Two-factor card (on/off,
with a setup link). Turning it on records an event and sends an alert.

### Acceptance criteria

- [x] Visiting setup creates an unconfirmed device. Two-factor isn't "on"
      until a valid code is submitted.
- [x] A wrong code leaves setup pending and the user unenrolled.
- [x] Ten recovery codes are displayed once and never shown again. Only
      hashes are stored.
- [x] Codes one step early or late are accepted, and two steps off are
      refused.
- [x] The QR code and setup key don't appear once setup is confirmed.
- [x] The hub's Two-factor card reflects the state.

---

## Phase 12: Two-step sign-in

**User stories**: 10, 11, 12, 13, 14, 15, 37 (recovery code used)

### What to build

For a user with confirmed two-factor, step 1 (password) stores only "user
X passed step 1 at time T" in the session and redirects to
`accounts:login_verify`. The user is not signed in. Step 2 accepts an
authenticator code or a recovery code. A used time step is refused
(replay), and each recovery code works once and triggers an alert. The
pending state expires after 5 minutes. Wrong codes count toward the same
cooldown as passwords, and five of them discard the pending sign-in. The
`next` redirect survives both steps. A password reset leaves two-factor
in force at the next sign-in.

### Acceptance criteria

- [x] After a correct password, a two-factor user is not authenticated on
      any page until step 2 succeeds.
- [x] Step 2 refuses a code from a time step already used.
- [x] A recovery code signs in once and is refused the second time, and
      its use sends an alert.
- [x] The pending sign-in is refused after 5 minutes (fixed clock).
- [x] Five wrong codes discard the pending state, and the account is then
      in cooldown at step 1.
- [x] `next` is honoured after step 2.
- [x] After a password reset, a two-factor user still has to pass step 2.
- [x] Users without two-factor sign in exactly as before.

Built with one addition the plan didn't list: Django's `/admin/login/`
signs in on the password alone, so it now redirects to the store's
sign-in page (keeping `next`). Every sign-in, the admin's included, goes
through both steps.

---

## Phase 13: Managing two-factor

**User stories**: 25, 26, 34, 35, 37 (2FA off, codes regenerated)

### What to build

For two-factor users, every re-authentication field becomes "Current
password or authenticator code" and passes if either matches. It accepts
authenticator codes but not recovery codes, and codes go through the same
replay check. The disable page takes both a password and a code, deletes
the device and recovery codes, records the event and sends an alert.
Superusers are refused. The recovery-codes page re-authenticates, replaces
the whole set, shows the new codes once, records the event and sends an
alert.

### Acceptance criteria

- [x] Each re-auth form (username, email, password, sign out others,
      regenerate codes) accepts a valid current code in place of the
      password.
- [x] Re-auth refuses a recovery code and a code already used at sign-in
      in the same time step.
- [x] Disable fails with only the password or only the code, and succeeds
      with both.
- [x] A superuser can't disable two-factor. The page and its POST both
      refuse.
- [x] Regenerating invalidates every old code and shows exactly 10 new
      ones once.

Built with three details the plan didn't spell out. An answer shaped like
a code (six digits) is checked last, once the rest of the form is valid,
so a typo elsewhere doesn't spend it, as the 2026-10-07 amendment already
does for the separate code field. A wrong answer is recorded once, as a
failed two-factor code if it was checked as one and as a failed sign-in
otherwise. Signing out one device takes a code too, since it uses the
same re-authentication form. The hub's Two-factor card now shows how many
recovery codes are left and links to both pages, with "Turn off" hidden
from superusers.

---

## Phase 14: Superuser two-factor gate and seed

**User stories**: 39, 53

### What to build

A middleware sends any signed-in superuser without confirmed two-factor
to the setup page. It exempts only setup, sign-out and static/media, so
`/admin/` is gated too. Promoting a user takes effect on their next
request. The seed enrols nobody, so the seeded `admin` is walked through
setup at first sign-in after every `seed`.

### Acceptance criteria

- [x] An unenrolled superuser is redirected from the storefront, the back
      office and `/admin/` to setup.
- [x] Setup, sign-out and static/media remain reachable.
- [x] An enrolled superuser and every non-superuser are unaffected.
- [x] Promoting a user to superuser gates their next request.
- [x] After `seed`, no two-factor devices or recovery codes exist, and
      signing in as `admin` lands on setup.

Built with two details the plan didn't spell out. The seed now deletes
every two-factor device and recovery code, not only those of its own
accounts, so a demo sign-up that turned two-factor on can't leave a
secret in the committed `db.sqlite3`. On the setup page, a superuser
sees why they're there ("Administrator accounts must use two-factor
authentication") and no "Cancel" link, which would only bounce them
back.

---

## Phase 15: Admin visibility

**User stories**: 40, 41

### What to build

Superusers get a "User security" link on the Account hub and a
superuser-only "User security" tab in the back-office tab rail, both
opening the admin's user list. `UserAdmin` gains read-only list columns
and filters for email verified, two-factor on, and locked / cooling down.

### Acceptance criteria

- [ ] Superusers see the link on the hub and in the tab rail. Staff and
      customers see neither.
- [ ] The user list shows correct values for verified, 2FA on, and locked
      / cooling down.
- [ ] Each of those can be filtered.

---

## Phase 16: Admin override actions

**User stories**: 44, 46, 47, 48, 49 (send reset link), 50, 51

### What to build

Six user-list actions: mark email verified, reset two-factor (deletes
device and recovery codes), clear sign-in cooldown, lock, unlock and send
password reset link. Each override records the matching event with the
admin as actor and sends the owner the matching alert. Actions skip the
acting admin's own account and any superuser, with a warning that names
those skipped. Only superusers can use them.

### Acceptance criteria

- [ ] Each action changes the target state and records an event with the
      admin as actor.
- [ ] Each action sends the owner its alert. Email-less owners are skipped
      silently.
- [ ] Selecting yourself or another superuser skips them, and the warning
      names them.
- [ ] Clearing a cooldown lets the user sign in at once. Earlier failures
      no longer count.
- [ ] A locked user's existing session is signed out and sign-in is
      refused with the generic message. Unlock restores access.
- [ ] Staff who aren't superusers can't run any of the actions.

---

## Phase 17: Admin direct edits

**User stories**: 45, 49 (set password), 51

### What to build

On a user's change page, editing username or email takes effect
immediately, under the same identity rules. The email counts as verified,
and the old address gets its notice. Django's existing set-password form
is kept, and it is now logged and alerted. On a superuser's change page,
username, email, active and password are read-only, and the set-password
form refuses.

### Acceptance criteria

- [ ] An admin email edit sets the email, marks it verified, records the
      event and notifies the old address.
- [ ] An admin username edit records the event with old and new values,
      and an `@` or case-insensitive duplicate is refused.
- [ ] Setting a password via the admin records the event and alerts the
      owner.
- [ ] On a superuser's change page those fields are read-only, and the
      set-password form refuses, including for the acting admin's own
      account.

---

## Phase 18: Break-glass, settings and documentation

**User stories**: 52, 54

### What to build

`manage.py reset_2fa <username>` deletes the device and recovery codes on
any accout to the new PRD. Finally,
`seed` is run before `db.sqlite3` is committed.

### Acceptance criteria

- [ ] `reset_2fa` works on a superuser, logs the event with a null actor,
      and fails cleanly for an unknown username.
- [ ] The app runs with no `.env`. Each cookie setting can be overridden
      from `.env`.
- [ ] `docs/ACCOUNTS.md` exists and CLAUDE.md points to it.
- [ ] The core PRD carries a dated amendment rather than a rewrite.
- [ ] `uv run pytest` is green and `uv run ruff check .` is clean.
- [ ] The committed `db.sqlite3` contains no two-factor devices.

---

## Amended 2026-10-07: the profile menu and profile pictures

Per the PRD's amendment of the same date. Built alongside phase 8.

- [x] The navbar shows a profile menu (picture, time-of-day greeting,
      name, Account and Edit profile links, Sign out) in place of
      "Account", "Hi, …" and the separate Sign out button. Visitors don't
      see it.
- [x] Orders, Wishlist and Cart are labelled icons to the left of the
      profile menu, which sits at the far right.
- [x] Sign-up takes an optional first and last name, and Edit profile
      changes them.
- [x] An uploaded picture is validated by `products/images.py`, stored as
      one 180 × 180 WebP, and can be replaced or removed; a replaced,
      removed or deleted account's file is deleted on commit.
- [x] Without a picture, or with its file missing, the silhouette
      placeholder is shown.

## Amended 2026-10-07: "mark email verified" brought forward

Per the PRD's amendment of the same date, phase 16's "mark email
verified" action and phase 15's "Email verified" column are built during
phase 8. Phases 15 and 16 build the rest around them.

- [x] A superuser can mark selected users' emails verified; it records an
      email-verified event with the admin as actor and emails the owner.
- [x] It skips the acting admin and other superusers, with a warning
      naming them, and leaves email-less accounts alone.
- [x] Staff who aren't superusers can't run it, even with user change
      permission.

## Amended 2026-10-07: asking for a code beyond sign-in

Per the PRD's amendment of the same date. Built after phase 11. Phase 12
is unchanged (sign-in always asks). Phase 13's "password or code" field
applies only when the security-changes choice is off; with it on, the
forms keep the separate password and code fields built here.

- [x] A two-factor user can choose to be asked for a code at checkout,
      on security changes, both or neither; both are off by default.
- [x] Saving the choices takes the password and a code, records a
      "Two-factor settings changed" event and alerts the owner.
- [x] With the security-changes choice on, every re-authentication form
      requires both the password and a code.
- [x] With the checkout choice on, no order is placed without a valid
      code.
- [x] A wrong code counts toward the cooldown, a code works once, and a
      mistake elsewhere on the form doesn't spend it.
- [x] Without two-factor on, nobody is asked, whatever is stored.
