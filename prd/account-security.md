# PRD: Account Management and Security

*Builds on `prd/core-platform.md`. The design interview behind it is
recorded in `prd/account-security-decisions.md` (Q1–Q22); decisions taken
while writing this PRD, which the interview left open, are marked
**(PRD-stage)**.*

---

## Problem Statement

A ThoughtTronix customer can create an account and sign in, and that is
the whole of their relationship with it. They sign in with a username
only, and nothing ever asked them for an email address. Once an account
exists, nothing about it can change: not the username, the email or the
password. A customer who forgets their password has no way back in. There
is no second factor, so a guessed or reused password is the only thing
between a stranger and a customer's order history, saved addresses and
cart. Nothing stops a stranger from guessing passwords as fast as they can
type.

The people responsible for the store see none of this. When something
goes wrong, such as a customer locked out, an account taken over, or an
email address nobody recognizes, an administrator has Django's admin
edit form and nothing else. They can't see what happened to an account
or when, can't undo it with a record left behind, and the admin's own
account, which can do anything, is protected by one password.

## Solution

Every account gets an **email address and a proper Account area**, and
every security-relevant change leaves a trail.

**For customers and staff.** Sign-up asks for an email. Sign-in accepts
a username *or* an email. A new **Account page** shows the account at a
glance: profile, password, two-factor status, addresses and recent
security activity. Each card links to a small page that changes one
thing: username, email, password or two-factor. Every change asks the
person to prove it's them first, with their current password or a code
from their authenticator app. A forgotten password is recovered by an
emailed link. **Two-factor authentication** with any standard
authenticator app (Google Authenticator, 1Password, Authy and others)
works offline and comes with one-time recovery codes for the day the
phone is lost. People are emailed when something important happens to
their account, and a "sign out of all other devices" button ends any
session they don't recognize.

**For the store.** Repeated wrong passwords trigger a short cooldown.
Every security event is written to a **tamper-proof audit log**.
**Superusers** get a set of overrides in Django's admin: verify an
email, reset two-factor, clear a cooldown, lock an account, set or reset
a password. Each override is logged and the account owner is emailed. No
superuser can use these overrides on their own account or on another
superuser's. Two-factor is **mandatory for superusers**.

Email is still delivered to the console only. Every flow that sends mail
works end to end with that, and the admin can mark an email verified so
demos never depend on a real inbox.

## User Stories

**Visitor (not signed in)**

1. As a visitor, I want sign-up to ask for my email address alongside my username and password, so that I have a way to recover my account.
2. As a visitor, I want sign-up to reject an email that another account already uses, compared case-insensitively, so that an email address always identifies exactly one account.
3. As a visitor, I want sign-up to reject a username containing `@` or one that differs from an existing username only by capitalisation, so that my username can never be mistaken for an email or for someone else's account.
4. As a visitor, I want my account to work as soon as I sign up, with a "confirm your address" link emailed to me, so that verification never stands between me and the store.
5. As a visitor, I want to sign in with either my username or my email, in any capitalisation, so that I don't have to remember which one I used.
6. As a visitor who has forgotten my password, I want to request a reset link by entering my email, so that I can get back into my account.
7. As a visitor requesting a reset, I want the same reply whether or not an account uses that email, so that nobody can use the form to find out who shops here.
8. As a visitor, I want a reset link to expire after one hour, work only once, and stop working if my password changes, so that an old email can't be used against me.
9. As a visitor who has just reset my password, I want every other session on my account signed out, so that whoever knew the old password loses access.
10. As a visitor with two-factor on, I want a password reset to still require my authenticator code at the next sign-in, so that a reset email alone can't take over my account.

**Signing in with two-factor**

11. As a user with two-factor on, I want sign-in to ask for my authenticator code after my password, so that a stolen password isn't enough.
12. As a user with two-factor on, I want to remain signed out until I've entered the code, with the half-finished sign-in expiring after five minutes, so that passing the password step grants nothing on its own.
13. As a user who has lost my phone, I want to enter one of my recovery codes instead of an authenticator code, so that I can still get in.
14. As a user, I want each recovery code to work only once, so that a code someone has seen is used up.
15. As a user, I want an authenticator code that has already been used to be refused, so that a code someone has watched me type can't be replayed.
16. As a user, I want sign-in to pause for 15 minutes after five wrong passwords or codes, so that nobody can keep guessing.
17. As a user, I want the cooldown to end on its own, so that a stranger can't lock me out of my account indefinitely.

**Signed-in user (customer, employee or admin): the Account page**

18. As a signed-in user, I want an "Account" link in the navigation in place of "Addresses", so that everything about my account is in one place.
19. As a signed-in user, I want the Account page to show my username, email and whether it's verified, when my password was last changed, whether two-factor is on, a link to my address book and my recent security activity, so that I can check my account at a glance.
20. As a user whose account has no email, I want a banner asking me to add one, so that I know I can't recover the account until I do.
21. As a user with an unverified email, I want an "Email not verified — resend link" prompt, so that I can confirm my address whenever I like.
22. As a user, I want to see my own last 10 security events, each with what happened, when and from which IP address, so that I can spot anything I didn't do.
23. As a user, I want events an administrator performed on my account to read "by ThoughtTronix support" without naming the admin, so that I know support was involved and staff stay anonymous.

**Proving it's you**

24. As a user, I want every sensitive change to ask for my current password, so that someone at my unlocked computer can't take over my account.
25. As a user with two-factor on, I want to be able to enter a current authenticator code instead of my password on those forms, so that I can confirm it's me with my phone.
26. As a user, I want turning two-factor off to require both my password and a code, so that someone who has only my unlocked phone can't remove the protection the phone provides.

**Changing username, email and password**

27. As a user, I want to change my username at any time, so that my account name fits me.
28. As a user, I want a new email to take effect only after I click a confirmation link sent to it, with my old address staying in effect until then, so that a typo can't cut me off from my account.
29. As a user, I want the confirmation link to expire after 24 hours and to be refused if the new address has been taken in the meantime, so that a stale link can't cause trouble.
30. As a user, I want my old address told when my email changes, so that I'd know if it wasn't me.
31. As a user, I want to change my password and stay signed in on this device while every other session is signed out, so that changing my password also ends any session I've lost track of.

**Two-factor setup and management**

32. As a user, I want to turn on two-factor by scanning a QR code, or typing a setup key, and then entering a working code before it switches on, so that I can never lock myself out with a half-finished setup.
33. As a user turning on two-factor, I want to be shown 10 recovery codes once, so that I can store them somewhere safe.
34. As a user, I want to regenerate my recovery codes, which invalidates the old set, so that I can replace codes I've used or exposed.
35. As a user, I want to turn two-factor off, so that I control my own account's security. Superusers can't.

**Sessions and alerts**

36. As a user, I want a "Sign out of all other devices" button, so that I can end sessions I don't recognize without changing my password.
37. As a user, I want an email whenever my password changes, two-factor is turned on, off or reset, my recovery codes are regenerated or one is used, my username changes, or my account is locked, so that I hear about changes I didn't make.
38. As a user, I want failed sign-ins never to email me, so that strangers can't fill my inbox by guessing.

**Superuser (admin)**

39. As a superuser, I want two-factor to be mandatory for my account, with every page, Django's admin included, redirecting me to setup until it's on, so that the most powerful account is never protected by a password alone.
40. As a superuser, I want a "User security" link on my Account page and in the back-office tab rail that opens the user list in Django's admin, so that I can reach the tools in one click. Other staff don't see the link.
41. As a superuser, I want the admin's user list to show whether each account's email is verified, whether two-factor is on, and whether it is locked or cooling down, so that I can assess an account quickly.
42. As a superuser, I want to browse the security audit log in the admin, filtered by user and event type, so that I can see what happened to an account and when.
43. As a superuser, I want the audit log to be read-only for everyone, me included, so that its history can't be rewritten.
44. As a superuser, I want to mark a user's email verified, so that testing and demos never depend on email delivery.
45. As a superuser, I want to edit a user's username or email directly, effective immediately, with the email counted as verified, so that I can fix an account a user can't fix themselves.
46. As a superuser, I want to reset a user's two-factor, which deletes their secret and recovery codes, so that someone who has lost both their phone and their codes can get back in.
47. As a superuser, I want to clear a user's sign-in cooldown, so that a customer who mistyped five times doesn't have to wait.
48. As a superuser, I want to lock and unlock an account, so that I can stop a compromised account indefinitely and on purpose.
49. As a superuser, I want to set a user's password, or send them a normal password-reset email, so that I can help them back in, ideally without ever knowing their password.
50. As a superuser, I want every override to be logged and to email the account owner, so that no override goes unrecorded.
51. As a superuser, I want overrides refused on my own account and on other superusers' accounts, with superusers' security fields read-only, so that no admin can quietly take over another admin.
52. As someone with server access, I want a `reset_2fa <username>` management command that works on any account, superusers included, so that a locked-out admin can be recovered by whoever runs the server.

**Developer**

53. As a developer, I want `seed` to produce a world where nobody is enrolled in two-factor and the seeded `admin` is walked through setup at first sign-in, so that both the mandatory and the opt-in flows can be demoed after every reset.
54. As a developer, I want the cookie security settings readable from `.env` with working defaults, so that the app still runs with no `.env` and can be hardened for deployment.

## Implementation Decisions

### Shape

- All new behaviour lives in the existing **`accounts`** app. No new app.
- **`accounts/security.py` is a fourth deliberate deep module**, with
  docstrings and type hints on every public function. It owns TOTP secret
  generation and provisioning, code checking (±1 time-step drift, replay
  protection via the last-used time step), recovery-code generation and
  checking, the sign-in throttle, recording `SecurityEvent`s, and sending
  alert emails. Views, forms and the admin call into it and contain no
  security logic of their own.
- **New dependencies:** `pyotp` (TOTP) and `segno` (QR code rendered as
  inline SVG, so no image files and no media). No `django-otp`, no
  `django-allauth`, no `django-axes`.
- Every new page is a class-based view with its own small form, following
  `PasswordChangeView`. No multi-form pages and no HTMX: this feature adds
  nothing to the HTMX inventory. Outcomes are reported with
  `django.contrib.messages`.

### Data model

- **`User`** gains a nullable **email-verified timestamp** and a small
  **session key field** that is mixed into Django's session auth hash.
  Rotating that field signs out every other session, as a password change
  does.
- **Email** becomes required on the sign-up form and **unique
  case-insensitively** through a functional unique constraint on the
  lowercased email. The constraint excludes blank emails, because
  accounts created before this feature have `""`. Emails are stored as
  entered and compared case-insensitively.
- **Username** gets a case-insensitive functional unique constraint and a
  validator rejecting `@`, applied at sign-up, on rename, and in the
  admin.
- The migration first checks existing rows for case-insensitive
  duplicate emails and usernames. If any exist, it **fails with a message
  that names them**. It never merges or renames accounts silently.
- **Two-factor device** (one per user): the TOTP secret (stored plain,
  see Further Notes), when setup was confirmed (null while setup is
  pending), and the last time step used, for replay protection. Two-factor
  is "on" when a confirmed device exists.
- **Recovery code** (ten per user): a hash of the code and when it was
  used. Codes are long and random, so a fast hash (SHA-256) is enough and
  checking ten of them stays instant. Regenerating replaces the whole
  set. **(PRD-stage)**
- **`SecurityEvent`**: affected user, actor, event type (fixed
  `TextChoices`), timestamp, IP address (`REMOTE_ADDR` only, because
  forwarded headers are spoofable without a known proxy), and a small
  JSON `details` field (for example `{"old": "casey", "new": "casey_r"}`).
  Passwords, codes, tokens and secrets are never stored.
- **Event types:** sign-up · sign-in succeeded · sign-in failed · 2FA code
  failed · password changed · password reset requested · password reset
  completed · email change requested · email change confirmed · email
  verified · username changed · 2FA enabled · 2FA disabled · 2FA reset ·
  recovery codes regenerated · recovery code used · account locked ·
  account unlocked · cooldown cleared · other devices signed out. An admin
  override is the matching event type with the admin as actor. No
  separate "override" type is needed.
- **What happens to `SecurityEvent` rows when a user is deleted
  (PRD-stage, open point 3):** `user` and `actor` are `SET_NULL`, and
  every event keeps a **username snapshot** of the affected account. The
  rest of the codebase cascades, but an audit log that disappears with
  the account it describes isn't an audit log.
- "Password last changed" on the Account page is the newest
  password-changed or reset-completed event. There is no extra column.
  An account with neither shows "Never changed".

### Authentication

- A custom **username-or-email backend** replaces `ModelBackend` in
  `AUTHENTICATION_BACKENDS`. It matches the identifier case-insensitively
  against username or email, which is unambiguous because usernames can't
  contain `@` and both are unique. It keeps `ModelBackend`'s permission
  behaviour and its refusal of inactive users.
- **Two-step sign-in.** Step 1 (the existing sign-in page, field
  relabelled "Username or email") checks the password. If two-factor is
  off, the user is signed in as today. If it's on, the session stores
  only "user X passed step 1 at time T". **The user is not signed in**.
  Step 2 asks for an authenticator code or a recovery code. The pending
  state expires after 5 minutes. The `next` redirect survives both steps.
- **Cooldown.** Five failures on one account within 15 minutes refuse
  further attempts until the oldest of them ages out. The count is a
  query on `SecurityEvent`. Failed passwords and failed 2FA codes count
  toward **the same total**, so restarting from step 1 doesn't buy fresh
  code guesses. Failures from before the most recent successful sign-in
  or "cooldown cleared" event don't count. Attempts refused during a
  cooldown aren't checked and aren't recorded as failures, so a cooldown
  can't extend itself. **(PRD-stage)**
- **Five wrong codes at step 2 discard the pending sign-in.** The user
  starts again from the password, and at that point the account is in
  cooldown.
- **Cooldown message (PRD-stage, open point 2):** a wrong password, an
  unknown account and a cooldown all show **one identical message**:
  "Those details didn't work. After several failed attempts, sign-in
  pauses for 15 minutes." It is honest about the rule without revealing
  whether the account exists.
- **Failed sign-ins for unknown identifiers (PRD-stage, open point 1):**
  logged with **no user and no attempted identifier**, only the IP
  address. People regularly type their password into the username field,
  so storing the identifier would break the "never store passwords" rule.
  The admin can still see guessing across many accounts from one IP.
- **Locked accounts** (`is_active = False`) are refused by the backend
  with the same generic message, and Django already treats their existing
  sessions as signed out.
- **Superuser two-factor gate:** a middleware redirects any signed-in
  superuser without confirmed two-factor to the setup page. It exempts
  only setup, sign-out and static/media, so `/admin/` is blocked too.
  Promoting a user to superuser makes the gate apply on their next
  request.

### Re-authentication ("prove it's you")

- Change username, change email, change password, regenerate recovery
  codes and sign out other devices each take one **"Current password"**
  field. For a two-factor user it is labelled "Current password or
  authenticator code" and passes if either matches.
- **Turning two-factor off takes both** a password field and a code field
  (Q7 exception, **confirmed**). Superusers can't turn it off at all.
- Re-authentication accepts authenticator codes, not recovery codes.
  Recovery codes are for getting in at sign-in. **(PRD-stage)**
- Wrong passwords and codes on these forms count toward the same
  cooldown as sign-in, so a hijacked session can't be used to guess the
  password. **(PRD-stage)**
- Codes used here go through the same replay check: a code spent at
  sign-in can't be reused on a form in the same time step.
- Enabling two-factor doesn't need re-authentication. Confirming a
  working code proves the person has the phone, and a superuser forced
  through setup straight after signing in shouldn't be asked for their
  password again.

### Email flows

- All mail goes through the existing console backend. One helper in
  `accounts/security.py` sends every alert, says what happened and when,
  ends with "Wasn't you? Contact support.", and **silently skips accounts
  with no email**. Sign-ins and failures never send mail.
- **Verifying an address:** at sign-up and on "resend link". The link is
  a signed, timestamped token from Django's signing machinery carrying
  user ID and email, with no new table. It **expires after 24 hours**
  **(PRD-stage)** and is dead once the email changes.
- **Changing email:** the user submits the new address with proof. A
  token carrying user ID, new address and current address is emailed to
  the *new* address and expires after 24 hours. On confirmation,
  uniqueness is re-checked, the email switches and is marked verified,
  and a notice goes to the *old* address. The token is refused if the
  account's current email no longer matches the one it carries.
- **Token links don't change anything on GET.** The link opens a page
  with a "Confirm" button that POSTs, so mail scanners that prefetch
  links can't confirm anything. They work without being signed in,
  because the token is the proof. **(PRD-stage)**
- **Password reset** uses Django's built-in reset views and token
  generator, restyled, with `PASSWORD_RESET_TIMEOUT` set to one hour. The
  matched email doesn't need to be verified. "Reset requested" is logged
  only when an account matched, and a completed reset sends an alert.
  Django already makes the token single-use and signs out every session
  on reset. The reset doesn't sign the user in.

### Account area: pages and URLs (PRD-stage, open point 4)

Every page requires sign-in except where noted. Everything lives under the
existing `accounts` namespace at `/accounts/`.

| Page | Path | Name |
|---|---|---|
| Account hub | `/accounts/` | `accounts:account` |
| Change username | `/accounts/username/` | `accounts:change_username` |
| Change email | `/accounts/email/` | `accounts:change_email` |
| Confirm email change (token, no sign-in) | `/accounts/email/confirm/<token>/` | `accounts:confirm_email_change` |
| Resend verification (POST) | `/accounts/email/verify/` | `accounts:send_verification` |
| Verify email (token, no sign-in) | `/accounts/email/verify/<token>/` | `accounts:verify_email` |
| Change password | `/accounts/password/` | `accounts:password_change` |
| Reset: request (no sign-in) | `/accounts/password/reset/` | `accounts:password_reset` |
| Reset: sent (no sign-in) | `/accounts/password/reset/sent/` | `accounts:password_reset_done` |
| Reset: set new (no sign-in) | `/accounts/password/reset/<uidb64>/<token>/` | `accounts:password_reset_confirm` |
| Reset: done (no sign-in) | `/accounts/password/reset/complete/` | `accounts:password_reset_complete` |
| 2FA setup | `/accounts/2fa/setup/` | `accounts:two_factor_setup` |
| 2FA off | `/accounts/2fa/disable/` | `accounts:two_factor_disable` |
| Regenerate recovery codes | `/accounts/2fa/recovery-codes/` | `accounts:recovery_codes` |
| Sign-in step 2 (pending sign-in only) | `/accounts/login/verify/` | `accounts:login_verify` |
| Sign out other devices (POST) | `/accounts/sessions/sign-out-others/` | `accounts:sign_out_others` |

Django's reset views redirect to un-namespaced URL names by default, so
each one gets an explicit namespaced success URL and email template. The
existing sign-up, sign-in, sign-out and address-book URLs stay as they
are.

- **Hub cards:** Profile (username, email, verified badge, change links),
  Password ("last changed …"), Two-factor (on/off, setup or disable,
  regenerate codes), Addresses (link to the unchanged address book),
  Recent security activity (last 10 own events), "Sign out of all other
  devices", and, for superusers only, **User security**.
- **Navigation:** the navbar's "Addresses" becomes "Account". The
  back-office tab rail gains a superuser-only **User security** tab
  linking to the admin's user list. Hiding the link is cosmetic only:
  the admin's own permission checks are the gate.
- **Recovery codes** are shown once, on the page that generated them, and
  never again.
- The QR code and the typed setup key appear only on the setup page,
  while setup is unconfirmed.

### Admin oversight

- `UserAdmin` gains read-only list columns (email verified, 2FA on,
  locked / cooling down) and filters for them.
- **Admin actions** on the user list: mark email verified · reset 2FA ·
  clear sign-in cooldown · lock · unlock · send password reset link.
  Editing username and email directly on the change form takes effect
  immediately, counts as verified and sends the old address its notice.
  Django's existing set-password form is kept and is now logged and
  alerted.
- **Guardrail (Q4, confirmed):** actions skip the acting admin's own
  account and any superuser target, with a warning message naming those
  skipped. On a superuser's change page, username, email, active and
  password are read-only and the set-password form refuses. Superusers
  change their own account through the Account area like everyone else.
- **Only superusers** can use the overrides or see the `SecurityEvent`
  admin. Staff who can reach `/admin/` get nothing new.
- **`SecurityEvent` admin** is read-only for everyone: no add, change or
  delete. It is filterable by event type, date and actor, and searchable
  by username snapshot.
- Every override records a `SecurityEvent` with the admin as actor and
  sends the matching alert.
- **Break-glass:** `manage.py reset_2fa <username>` deletes the user's
  device and recovery codes and logs a 2FA-reset event with no actor. It
  is the one path that works on a superuser. Django's existing
  `changepassword` covers the password.

### Settings

- `AUTHENTICATION_BACKENDS` lists the custom backend.
  `PASSWORD_RESET_TIMEOUT` = 3600.
- Read from `.env` with development defaults and listed in
  `.env.example`: `SESSION_COOKIE_SECURE` (default off),
  `CSRF_COOKIE_SECURE` (default off), `SESSION_COOKIE_AGE` (default two
  weeks).

### Seed

- Nobody is enrolled in two-factor. The seeded `admin` is forced through
  setup at first sign-in after every `seed`. `employee` and `customer`
  can opt in.
- The seed already gives every user a unique `@example.com` address.
  `admin` and `employee` are seeded as **verified** and `customer` as
  **unverified**, so the resend-link prompt can be demoed. **(PRD-stage)**
- Seeded users get a sign-up event each so the activity card isn't
  empty.

## Out of Scope

- Real email delivery. Console only, with the admin's "mark verified" in
  its place.
- "Trust this device for 30 days". A code is required at every sign-in.
- A cooldown between username changes.
- A "must change password at next sign-in" flag.
- Encrypting TOTP secrets at rest.
- Limiting password reset to verified emails. This is a one-line filter
  once real email exists.
- Account deletion or self-closure.
- Passkeys or WebAuthn, SMS codes, social sign-in.
- Rate-limiting password-reset or verification-email requests. With
  console mail there is no inbox to flood.
- Pruning or retaining the audit log on a schedule.
- Custom back-office pages for user management. The tools live in
  Django's admin.
- Any new permissions for staff (`is_staff`) who are not superusers.

## Further Notes

- **Superseded decisions.** The core PRD's "authentication is
  username-based — Django's default, unchanged" and "sign up with a
  username and password (no email)" are superseded. When this is built,
  add a dated amendment to `prd/core-platform.md` pointing here, as was
  done for discount codes, rather than rewriting it.
- **Documents updated during the build:** CLAUDE.md ("exactly three deep
  modules" becomes four, plus a "Read before…" pointer to a new
  `docs/ACCOUNTS.md`), `SignupForm`'s "No email" docstring, and the
  README (the demo `admin` now requires 2FA setup after each `seed`).
- **TOTP secrets are stored plain.** `db.sqlite3` is committed for
  grading, so **run `seed` before committing it**. That leaves nobody
  enrolled and no real secret in git history. Encrypting secrets with a
  key from `.env` is the upgrade path.
- **Known trade-off:** sign-up still tells a visitor when a username or
  email is taken. That is unavoidable for a form that must reject
  duplicates, and the reset form, where enumeration matters more, never
  does.
- **Testing priorities** (pytest, plain fixtures, per `docs/TESTING.md`):
  1. `accounts/security.py` first: code drift and replay rejection,
     recovery codes single-use, the cooldown count with its reset points,
     and alerts skipping email-less accounts.
  2. The backend: username or email, case-insensitive, inactive refused.
  3. The two-step sign-in: no session between steps, pending state
     expiring, five-code discard.
  4. Each re-authentication form, including disable-2FA requiring both.
  5. The email-change token: expiry, uniqueness re-check on confirm,
     refusal after the email changes.
  6. The superuser gate.
  7. Admin guardrails and the read-only `SecurityEvent` admin.
  8. The migration's duplicate check.
  Generate TOTP codes in tests with `pyotp` from the test device's
  secret, and use a fixed clock rather than sleeping.

---

## Amendment — escalating sign-in pauses (2026-10-07)

Made after phase 4 was built, at the user's request, once they had tried
the cooldown in a browser and found it gave no sense of how many attempts
were left or that the account had been paused. Three decisions above are
changed. The rest of the PRD stands.

- **Escalation (replaces the fixed cooldown; changes story 16).** Five
  failures within 15 minutes still start the first pause, but a pause
  now lasts a fixed time from the failure that started it, rather than
  until the oldest failure ages out. Once a pause has ended, a single
  further failure starts the next one: 15, then 30, then 60 minutes, and
  60 from then on. The ladder starts again after a successful sign-in, a
  "cooldown cleared" event, or when no pause has started in the last 24
  hours. Story 17 still holds: every pause ends on its own, and the
  one-hour cap bounds how long a stranger can keep someone out. Attempts
  refused during a pause are still neither checked nor recorded.
- **A new event type, "sign-in paused"** (`cooldown_started`), is recorded
  when a pause starts, with its length in `details`. It is how the ladder
  knows which rung it is on, and it shows the admin when an account was
  paused.
- **What the sign-in page says (refines the cooldown message).** Every
  refusal still shows one identical message, now just "Those details
  didn't work." Below it, the page says how many attempts are left, or
  that sign-in is paused and for how many more minutes. That line is
  built from **this browser's own history**, kept in its session against
  a keyed hash of what was typed, and never from the account's. An
  unknown username therefore counts down exactly as a real one does, and
  the page still doesn't reveal which accounts exist. The account's own
  history alone decides whether a sign-in is allowed, so the two can
  differ when attempts came from another browser.
- **One email per pause (changes story 38).** When a pause starts, the
  owner is emailed once, saying for how long and when they can sign in
  again, through the same alert helper and wording as every other alert.
  Ordinary failed sign-ins still never send mail, so a stranger can
  trigger at most one email per pause.

---

## Amendment — the device list (2026-10-07)

Made after phase 6 was built, at the user's request, once they had tried
"Sign out of all other devices" in a browser and found the Account page
gave no way to see what was signed in. Story 36 is extended; the rest of
the PRD stands.

- **A device list (extends story 36).** The Account page's Devices card
  lists every browser signed in to the account: a readable name taken
  from the user agent ("Firefox on Windows"), the IP address, when it
  signed in and when it was last active, with "This device" marked.
  Each browser is one device, however many windows or tabs it has open.
- **Signing out one device.** Every device but this one has a "Sign out"
  link to a confirm page that takes the current password, like "Sign out
  of all other devices", and counts a wrong answer toward the cooldown.
  GET changes nothing. The device is signed out on its next request and
  told why. A new event type, "Signed out a device" (`session_ended`),
  records it with the device's name in `details`.
- **How it works.** A `UserSession` row per signed-in browser, created at
  sign-in through `user_logged_in`, removed at sign-out, with its id kept
  in that browser's session. A middleware checks the row on every
  signed-in request and signs the browser out if it's gone; that is the
  whole mechanism for signing one device out. Django's session key is
  never stored, because it is a bearer credential. "Last active" and the
  IP are refreshed at most once a minute, and each refresh slides the
  session's expiry forward, so a row idle for `SESSION_COOKIE_AGE` has
  expired with its session and is no longer listed.
- **The session key field stays.** "Sign out of all other devices" and a
  password change now also delete the other rows, so the list never shows
  a device that is already signed out, but the rotation still catches any
  session without a row.
- **Not stored:** nothing beyond what the list shows. The user agent is
  kept only to name the device.

---

## Amendment — the profile menu and profile pictures (2026-10-07)

Made after phase 8 was built, at the user's request, once they had used
the navbar in a browser. The navbar's separate "Account" link and "Hi,
username" greeting become one profile menu, and accounts gain a name and
a picture to fill it. Story 18 is extended; the rest of the PRD stands.

- **The profile menu (extends story 18).** Signed-in users see their
  profile picture in the navbar in place of "Account" and "Hi, …".
  Opening it shows the picture, a greeting by time of day in the store's
  time zone ("Good evening, Casey", from the first name, or the username
  without one), their full name (or username), and links to the Account
  page and a new Edit profile page, then "Sign out". The menu is
  CSS-only: no JavaScript and nothing added to the HTMX inventory.
- **The navbar's layout.** The profile menu sits at the far right. Orders,
  Wishlist and Cart become larger icons to its left, each labelled for
  screen readers and titled for a hover hint, with the cart keeping its
  count badge. Staff still see a "Back office" text link before them.
- **A name.** Sign-up gains optional first- and last-name fields. The
  Edit profile page changes them at any time. A name is not a security
  setting, so it needs no re-authentication and records no
  `SecurityEvent`.
- **A profile picture.** Uploaded on the Edit profile page, held to the
  same rules as product photos except that the smallest side need only be
  180 pixels, then cropped to its centre square and stored as one 180 ×
  180 WebP. It can be replaced or removed. Without one, a neutral
  silhouette placeholder is shown. The picture goes through
  `products/images.py` like every other image, follows its "never load a
  missing file" rule, and is deleted with the account.
- **Not included:** cropping by hand, pictures of other people in the
  admin, Gravatar, or any way for other customers to see a picture.

## Amendment — "mark email verified" brought forward (2026-10-07)

Made during phase 8, at the user's request, so that demos needn't depend
on reading console mail. Phase 16's **mark email verified** admin action
is built now, exactly as story 44 and the admin-oversight rules describe:
superusers only, skipping the acting admin and every superuser with a
warning naming them, recorded with the admin as actor, and the owner
emailed. The user list gains its "Email verified" column (story 41) with
it. The other five overrides stay in phase 16.
