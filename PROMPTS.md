# PROMPTS.md — AI Usage Log

This file is the record of AI use on this codebase. At the end of every
agent session, direct the agent to write the session log with this prompt:

> Append a session log to PROMPTS.md at the repo root, under today's date,
> newest entry at the top. Record every prompt I gave you this session, in
> order, including any corrections. End the entry with a short summary:
> the outcome, any places where I deviated from a recommended answer or
> asked follow-up questions, and anything that went sideways.

Two rules:

- Entries are added only by that prompt, never unprompted.
- New entries go at the top. Never rewrite or delete an old entry — the
  log is part of your work, and an honest log of a session that went
  sideways is worth more than a tidy one.

Each entry has this shape:

    ## YYYY-MM-DD — <one-line summary>

    ### Prompts
    1. ...

    ### Summary
    - **Outcome:** what was built and what was kept
    - **Deviations:** recommendations overridden, follow-up questions asked
    - **Sideways:** failures, wrong turns, and how they were caught

---

## 2026-10-07 — Account security, Phase 9: change email by confirmation link, plus an Actions section and animated icons

### Prompts

1. "@prd/account-security.md @plans/account-security.md Implement phase 9"
2. "Ok I would like to mke some changes I would like to combine the Change
   password Change username and Change email into one section called
   actions use iconography where approprite to distinguish between each of
   the actions. Also incude animated Iconography for the other sections of
   this as well to make it look cleaner."
3. "How can I test this in the browser" (with phase 9's "Before
   confirmation, the old email stays in effect for sign-in and reset"
   criterion selected in the plan)
4. "append the conversation to PROMPTS.md"

### Summary

- **Outcome:** Prompt 1 built phase 9 of `plans/account-security.md` and
  ticked its five acceptance criteria:
  - **The token.** `accounts/security.py` gained an `EmailChange`
    dataclass, `email_taken`, `make_email_change_token`,
    `email_change_for_token`, `request_email_change` and `change_email`.
    Like the verification link, the token is a `signing.Signer` object
    with no table. It carries the user id, the old and new addresses and
    the issue time. It is refused when tampered with, older than 24 hours,
    for a deleted account, or once the account's email no longer matches
    the old address it carries. That last rule also means confirming one
    link kills every other pending one.
  - **The switch.** `change_email` re-checks uniqueness inside a
    transaction, and the database constraint backs it up through a caught
    `IntegrityError`. It then sets the email and `email_verified_at`,
    records "Email changed" with `{"old", "new"}` and emails the notice to
    the *old* address. It takes an optional `actor`, so phase 17's admin
    edit can reuse it, and with an admin as actor the notice reads "by
    ThoughtTronix support". To send to the old address, `send_alert`
    gained a `to=` argument; every existing caller is unchanged.
  - **The pages.** `accounts:change_email` (`ChangeEmailForm`, built on
    `ReauthenticationForm`, so a wrong password counts toward the
    cooldown) mails the link to the new address, records "Email change
    requested" and changes nothing. `accounts:confirm_email_change` shows
    a Confirm button on GET, switches only on POST, needs no sign-in, and
    says "That address is taken" when another account got there first.
    The hub's Profile card and the no-email banner link to the new page.
  - **Tests.** `accounts/test_change_email.py` has 31 tests. "The old
    email still works for reset" is checked through Django's
    `PasswordResetForm.get_users`, because the reset pages arrive in
    phase 10.

  Prompt 2 restructured the Account page. Change password, Change
  username and Change email left their cards and became three tiles in a
  new **Actions** section: a key, an @ and an envelope, each in its own
  colour, with a chevron. A new `accounts/partials/_icon.html` renders
  Heroicons outline icons by name (the navbar's set). New rules in
  `assets/css/source.css` make each icon draw itself in on load, using
  `pathLength="1"` and a sliding stroke dash, and play a small motion
  (wiggle, bob, pop, spin, tilt, nudge) when its card is hovered or
  focused. Everything stands still under `prefers-reduced-motion`. Every
  section heading got an icon, and "This device" got a pulsing status
  dot. The device list shows a phone or computer icon, from a new
  `UserSession.is_phone`. The empty activity state's 🛡️ emoji became a
  drawn shield. `docs/TEMPLATES.md` documents the partial and the CSS.

  Prompt 3 changed no code. It produced a browser walkthrough using the
  seeded `customer`, covering:
  - asking for the change and its refusals;
  - the old email still signing in before confirmation;
  - confirming, and the notice in the console;
  - the reused, taken, superseded, expired (minted in `manage.py shell`
    with a backdated `at=`) and tampered links;
  - an email-less account adding one;
  - the admin's event list.

  The suite went from 725 to 761 tests. Ruff is clean and nothing was
  committed.

- **Deviations:** No questions were asked in either building prompt.
  These defaults were taken and reported:
  - The confirmation page names the account's username.
  - Recapitalising your own address is allowed, as for usernames, and
    the identical address is refused.
  - The request event stores both addresses in `details`.

  In prompt 2:
  - "Edit profile" stayed on the Profile card rather than joining
    Actions, since it isn't a security change.
  - The Password card was kept, showing only "last changed".
  - The phone-or-computer device icon was a small addition the prompt
    didn't name.

  The Actions redesign got no dated amendment in the PRD or plan, unlike
  the earlier UI changes made in this feature.

- **Sideways:**
  - **The first draft of a test held a junk line**
    (`ask(...) if False else ask(...)`). The agent caught it and rewrote
    it, with the `ask` helper taking request kwargs, before the tests
    first ran. All 31 then passed on the first run.
  - **The redesign broke two existing tests.**
    - The icon partial's trailing newline split the badge's
      `>Verified<`, so "Verified" now sits in its own span.
    - The new Actions test counted the no-email banner's "Add an email"
      link. The seeded-style `customer` fixture has no email, so the
      test now checks the Actions section against the summary cards
      only.
  - **`db.sqlite3` showed as modified after prompt 1** even though the
    agent never touched it, most likely because of the user's running
    dev server. `seed` still needs to run before it is committed.
  - **`tailwind build` reported the stylesheet already up to date.** The
    user's watcher had rebuilt it, and the agent confirmed the new
    classes were in the compiled CSS.
  - **The agent never opened the pages in a browser.** The animations are
    unchecked by eye.

## 2026-10-07 — Account security, Phase 8: email verification, plus a profile menu and profile pictures

### Prompts

1. "@prd/account-security.md @plans/account-security.md Implement phase 8"
2. "how can I test this in a browser"
3. "Ok so few things that I noticed I tried using the verify link sent in
   console but I keep on getting amessage stating that the link does not
   work. Also I do not have a workaround in the admin panel for quicly
   verifying emails without having to go through emails. Additionally
   this is not part of this PRD but I would like to combine the Account
   and the Greeting and include a customer profile image instead and have
   a simple placeholder image if they do not upload one image profile
   images should be 180 by 180 and allow users to change them by
   uploading a picture, also in the profile menu it should show their
   actual name as well and a personalized greeting"
4. "Ok I would also like to change the layout of the topbar menu can you
   make the gin out option in the profile icon dropdown menu and just have
   simple larger icons that represent the orders wishlis and cart the
   profile menu should be all the way to the right and the other icons for
   the other menus should be to the left of it."
5. "Append this conversation to PROMPTS.md"

### Summary

- **Outcome:** Prompt 1 built phase 8 of `plans/account-security.md` and
  ticked its five acceptance criteria:
  - **The model.** `User.email_verified_at` (migration `0008`) and an
    `email_verified` property.
  - **The token.** `accounts/security.py` gained
    `make_verification_token`, `user_for_verification_token`,
    `send_verification_email` and `mark_email_verified`. The token is a
    `signing.Signer` object carrying user id, email and issue time, with
    no table. It is refused when tampered with, older than 24 hours, for
    a deleted account, or for an email the account no longer has.
  - **The pages.** Sign-up sends the link and the account works at once.
    `accounts:verify_email` shows a Confirm button on GET and verifies
    only on POST, without sign-in. `accounts:send_verification` is the
    hub's POST-only "resend link". The Profile card shows a Verified
    badge or "Email not verified — resend link".
  - **The seed.** `admin` and `employee` are seeded verified, `customer`
    unverified.

  Prompt 2 changed no code. It produced a browser walkthrough: sign-up and
  the console link, GET-changes-nothing, signed-out confirmation, resend,
  tampered, changed-email and expired links (the last minted in `manage.py
  shell` with a backdated `at=`), and the admin's event list.

  Prompt 3 produced three changes:
  - **The broken link (a real bug).** Django 6 builds mail with Python's
    modern email API, which sends any body line over 78 characters as
    quoted-printable. The console backend printed that raw, so the link
    was soft-wrapped with `=` and couldn't be copied. `config/mail.py`
    adds a console backend that prints with a 998-character line limit, so
    bodies print as plain 8-bit text, and `EMAIL_BACKEND` points to it.
    What a real backend would send is unchanged. A regression test reads
    the link out of the console output and follows it.
  - **The admin shortcut.** Phase 16's "Mark email verified" action and
    phase 15's "Email verified" column were brought forward, with phase
    16's rules: superusers only (an `override` action permission checking
    `is_superuser`), skipping the acting admin and every superuser via a
    new `security.overridable`, recorded with the admin as actor, and the
    owner emailed. Email-less accounts are left alone.
  - **The profile menu and pictures.** `User.avatar` (migration `0009`),
    `display_name` and a time-of-day `greeting`. `products/images.py` gained
    `validate_avatar`, `set_avatar`, `remove_avatar` and `avatar_picture`.
    `validate_image`'s checks were pulled out into a shared `_checked` and
    `_decoded`, with every product message kept word for word. Pictures
    are center-cropped to one 180 × 180 WebP. A silhouette SVG is the
    placeholder, and a `post_delete` receiver removes a deleted account's
    file. Sign-up takes optional first and last names. A new Edit profile
    page (`accounts:edit_profile`) changes the name and picture through
    `ProfileForm`. The navbar's "Account" and "Hi, …" became one CSS-only
    avatar dropdown.

  Prompt 4 rearranged the navbar: Orders, Wishlist and Cart became larger
  labelled SVG icons (the cart's lives in `_cart_badge.html`, so HTMX's
  out-of-band swap keeps it), the profile menu moved to the far right,
  and Sign out moved into it as a button submitting a hidden form by id.

  Paperwork: two dated amendments in the PRD and the plan (the profile
  menu and pictures; "mark email verified" brought forward), a Profile
  pictures section in `docs/IMAGES.md`, and CLAUDE.md's images pointer
  now mentions profile images. The suite went from 688 to 725 tests. Ruff
  is clean, the CSS was rebuilt, and nothing was committed.

- **Deviations:** For prompt 3, the agent asked four questions before
  building the profile feature, and the user took the recommended answer
  each time except for the placeholder, where no recommendation was given:
  - **Name source:** optional first and last name at sign-up, editable on
    an Edit profile page (recommended).
  - **Greeting:** by time of day (recommended).
  - **Placeholder:** a generic silhouette, not initials on a circle.
  - **Paperwork:** a dated amendment to the existing PRD and plan
    (recommended).

  Defaults taken without asking and reported: the picture is
  center-cropped (no manual crop); names and pictures need no
  re-authentication and record no `SecurityEvent`; the "Email verified"
  event stores the confirmed address in `details`; "Back office" stays a
  text link in prompt 4. The greeting follows `TIME_ZONE = "UTC"`, so it
  is three hours ahead of the user's UTC−3. Switching the zone was
  offered, not done.

- **Sideways:**
  - **The console link bug shipped in prompt 1 and was caught only by
    the user in a browser.** The tests read `mail.outbox`, which holds
    messages before encoding, so they never saw what the console printed.
    The new test goes through the real console output.
  - **A token-age test failed on its first run.** Tokens store whole
    seconds, so "exactly 24 hours" from a microsecond-precise `now` was a
    fraction of a second late. The test now pins a whole-second clock,
    and a token can expire up to a second early.
  - **The agent's first draft of the console regression test was wrong.**
    It monkeypatched `mail.get_connection` and then `del`eted it from the
    module. It was rewritten with the `settings` and `capsys` fixtures
    before it ever ran.
  - **The agent accidentally ran `git stash -- config/settings.py`**,
    reverting the backend setting. It noticed at once, ran `git stash
    pop`, and checked that the user's staged plan file was untouched.
  - **The plan was already damaged.** Before the session began, the
    user's staged `plans/account-security.md` unticked phases 3–7,
    dropped the phase 4 and 6 amendment sections, and garbled phase 18's
    "What to build". The agent flagged it and didn't repair it. Phase 8's
    boxes and the new amendments were added on top of that version.
  - **The pages were not opened in a browser by the agent.** `seed`
    wasn't run, and still needs to run before `db.sqlite3` is committed.

## 2026-10-07 — Account security, Phase 7: change username

### Prompts

1. "@plans/account-security.md @prd/account-security.md Implement phase 7"
2. "how can I test this within the browser"
3. "Append this session to PROMPTS.md"

### Summary

- **Outcome:** Prompt 1 built phase 7 of `plans/account-security.md` and
  ticked its four acceptance criteria:
  - **The page.** `/accounts/username/` (`accounts:change_username`) asks
    for the current password, then the new username. The Account page's
    Profile card gained a "Change username" button.
  - **The form.** `ChangeUsernameForm` is built on phase 6's
    `ReauthenticationForm`, so a wrong password counts toward the
    cooldown, and while the account is paused nothing is checked. The new
    name is run through the username model field's own validators (no
    `@`) and refused if another account has it in any capitalisation.
    Recapitalising your own name is allowed.
  - **The trail.** `security.username_changed` records the event with
    `{"old": …, "new": …}` in `details` and sends the alert. It takes an
    `actor`, so phase 17's admin edit can reuse it.
  - **Staying signed in.** The username isn't part of the session auth
    hash, so a rename signs no device out. A test checks a second browser
    stays signed in.

  The suite went from 644 to 665 tests, all 21 new ones in
  `accounts/test_change_username.py`. Ruff is clean and no migration was
  needed. Nothing was committed.

  Prompt 2 changed no code. It produced a browser walkthrough using the
  seeded `customer`: names that should be refused (a seeded customer's
  name in capitals, an `@`, a space, the current name), a wrong password
  and the five-failure pause, a real rename with its alert in the
  `runserver` terminal, a second browser that stays signed in, signing in
  with the new name, and the event in the admin. `seed` cleans up.

- **Deviations:** no questions were asked; the agent proceeded on
  defaults and reported them:
  - **The current username is refused** ("That's already your
    username."), so a no-op can't log an event or send an email.
  - **The form doesn't touch the user until it saves.** A `ModelForm` on
    `request.user` would have written a refused name onto the user while
    validating, and the navbar would have shown it on the re-rendered
    page. A test covers this.
  - **Wrong re-auth passwords stay "Sign-in failed"**, with
    `change_username` in `details`, as phase 6 decided.

- **Sideways:** Nothing broke. Every new test passed on its first run,
  and the full suite stayed green. `ruff format` reflowed four files after
  that run, so the `accounts` tests (221) were run again and passed. The
  pages weren't opened in a
  browser by the agent; prompt 2's walkthrough is how they're meant to be
  checked. `seed` still needs to run before `db.sqlite3` is committed.

## 2026-10-07 — Account security, Phase 6: change password, sign out other devices, and a device list

*The same session as the Phase 5 entry below, continued; its first three
prompts are logged there.*

### Prompts

1. "@prd/account-security.md @plans/account-security.md Implement phase 6,
   try to utilize the existing template made from phase 5"
2. "How can I test this in the browser"
3. "Ok for the devices I cannot see another session even when I am on
   multiple browser windows can you make it to where I can see the
   devices that are currently signed in as well as for how long and
   choose to indavidually sign them out."
4. "add session chats to PROMPTS.md"

### Summary

- **Outcome:** Prompt 1 built phase 6 of `plans/account-security.md` and
  ticked its five acceptance criteria:
  - **The session key.** `User.session_key` (migration `0006`) is mixed
    into the session auth hash by overriding `_get_session_auth_hash`, so
    the `SECRET_KEY_FALLBACKS` variant is covered too.
    `rotate_session_key()` signs out every other session without touching
    the password.
  - **Prove it's you.** `ReauthenticationForm` is the shared "Current
    password" field. It checks through the new
    `security.confirm_identity`: a wrong answer is recorded as a failed
    sign-in with `{"reauthentication": <purpose>}` in `details` and
    counts toward the cooldown. While the account is paused, nothing is
    checked or recorded.
  - **Change password.** `PasswordChangeForm` is built from Django's
    `SetPasswordMixin` and `ReauthenticationForm` rather than from
    Django's own `PasswordChangeForm`. That form checks the old password
    itself, which would have bypassed the cooldown.
    - The view subclasses Django's `PasswordChangeView`, so this session
      stays signed in and the new password ends every other one.
    - `security.password_changed` records the event and sends the alert.
  - **Sign out of all other devices.** `security.sign_out_other_sessions`
    rotates the key, keeps this session and records the event.

  "Utilize the existing template" was read as building onto the phase 5
  Account page rather than adding a separate page:
  - The Password card gained a Change password button.
  - A Devices card holds the sign-out form.
  - `SignOutOthersView` subclasses `AccountView`, so a wrong password
    re-renders the whole Account page with the error under the field.

  The suite went from 590 to 615 tests, all 25 new ones in
  `accounts/test_password_and_sessions.py`.

  Prompt 2 changed no code. It produced a browser walkthrough: a normal
  window plus a private one as two devices, alert emails in the
  `runserver` terminal, five wrong answers to trip the pause, and `seed`
  to clean up.

  Prompt 3 added a device list:
  - **The model.** A `UserSession` row per signed-in browser (migration
    `0007`, which also adds a "Signed out a device" event type). It is
    created on `user_logged_in`, deleted on `user_logged_out`, and its id
    is kept in the browser's session.
  - **The middleware.** `UserSessionMiddleware`, through
    `security.track_session`, signs a browser out once its row is gone,
    with a message saying why. It refreshes "last active" and the IP at
    most once a minute, and each refresh slides the session's expiry
    forward, so idle rows expire with their sessions.
  - **The Devices card.** It now lists each browser: a name from the
    user agent ("Firefox on Windows"), the IP, when it signed in, when it
    was last active, and "This device" marked.
  - **Signing out one device.** Any other device can be signed out on
    its own through a confirm page that takes the current password.
  - **Clearing rows.** "Sign out of all others" and a password change
    now also delete the other rows.

  The PRD has a dated amendment and phase 6 of the plan an amended
  section with five new criteria. The suite went from 615 to 644 tests,
  all 29 new ones in `accounts/test_devices.py`. Ruff is clean, and
  migrations `0005` through `0007` were applied to the local database.
  Nothing was committed.

- **Deviations:** no questions were asked; the agent proceeded on
  defaults and reported them:
  - **Device sign-out needs the password.** Signing out a single device
    requires the current password, consistent with "Sign out of all
    other devices" and story 24. The user was told it could become one
    click.
  - **No new event type for re-auth failures.** Wrong current passwords
    are logged as "Sign-in failed" with the form named in `details`,
    because the PRD's list of event types is fixed. They therefore read
    as "Sign-in failed" on the activity card.
  - **No alert for signing out devices.** Neither signing out other
    devices nor signing out one device sends an email, because story
    37's list of alerts doesn't include them.
  - **Session keys are never stored.** The device list keys on its own
    row id, because a Django session key is a credential.

- **Sideways:**
  - **The device problem was partly a misunderstanding.** Windows of one
    browser share cookies, so they were always one session. The build
    added the list, and the reply explained that a second browser or a
    private window is needed to see a second device.
  - **A leftover line.** The first draft of the password-change tests had
    a stray `... if False else None` line, removed before the first run.
    Every new test passed on its first run.
  - **Two behaviour changes worth knowing:**
    - Every existing dev session was signed out once, because the
      session hash changed.
    - Sessions now last two weeks from last use rather than from sign-in.
  - **A pending migration.** Phase 4's migration `0005` had never been
    applied locally. It went in along with `0006`.
  - **No browser check.** The agent didn't open the pages itself; prompt
    2's walkthrough is how they're meant to be checked.
  - **`seed` not run.** It still needs to run before `db.sqlite3` is
    committed, as phase 18 requires.

## 2026-10-07 — Account security, Phase 5: the Account page and navigation

### Prompts

1. "@plans/account-security.md @prd/account-security.md Implement phase 5"
2. "How can I test this in the browser"
3. "Append the session conversation to PROMPTS.md"

### Summary

- **Outcome:** Phase 5 of `plans/account-security.md` was built and its
  six acceptance criteria ticked:
  - **The page.** `AccountView` at `/accounts/` (`accounts:account`)
    requires sign-in, and anonymous visitors go to sign-in with `next`
    set. `templates/accounts/account.html` has four cards:
    - **Profile:** username and email.
    - **Password:** "Last changed …" or "Never changed".
    - **Addresses:** a count, and a link to the address book, which is
      unchanged.
    - **Recent security activity:** the user's own last 10 events, newest
      first, with what happened, when and the IP. It has a designed empty
      state.

    Accounts with a blank email see a banner asking them to add one.
  - **The model side.** `User.password_last_changed` reads the newest
    password-changed or reset-completed event through a new
    `SecurityEventQuerySet.password_changes()`. There is no new column.
    `SecurityEvent.by_support` is true only when someone other than the
    owner acted. The template reads that and never `actor`, so the page
    can't name an admin. Events with no actor, such as a failed sign-in,
    aren't marked as support.
  - **The navbar.** "Addresses" became "Account".

  The suite went from 572 to 590 tests, all 18 new ones in
  `accounts/test_account_hub.py`. The admin-override test uses a
  distinctive username and email so their absence from the page proves
  something. Ruff is clean, and `makemigrations --check` found nothing,
  because the custom manager isn't used in migrations. Nothing was
  committed.

  Prompt 2 changed no code. It produced a browser walkthrough:
  - **Start clean:** `seed`, then `tailwind runserver`. The watcher is
    needed because the hub uses classes no earlier page did.
  - **Check the page:** the redirect and the navbar, then a few deliberate
    wrong passwords (fewer than five) to fill the activity card.
  - **Shell-written events:** a password change and an admin-cleared
    cooldown, because neither can be triggered from the UI until phases 6
    and 16. Twelve "Signed in" events check the cap. The walkthrough used
    those rather than failures, which would have paused the account.
  - **The banner:** blanking the email shows it.
  - **Clean up:** a final `seed`, because the shell events land in the
    committed `db.sqlite3`.

- **Deviations:** no recommendations were offered and no questions were
  asked. Two parts of the phase description were left for the phases that
  make them possible:
  - **The verified badge.** The phase lists one on the Profile card, but
    the email-verified timestamp doesn't exist until phase 8, whose own
    criteria cover the badge.
  - **The banner's link.** It has no "add an email" link, and the Profile
    card has no change links, until phases 7 and 9 build those pages.

- **Sideways:**
  - **A PROMPTS.md entry almost went in unprompted.** The agent was about
    to add one after the build, as earlier phases had, but read this
    file's rule that entries are added only on request and left it out.
    This entry is the result of prompt 3.
  - **Ruff format.** It reformatted two files after the first run.
  - **No browser check.** The agent didn't open the page itself. Prompt
    2's walkthrough is how it's meant to be checked.
  - **`seed` not run.** It still needs to run before `db.sqlite3` is
    committed, as phase 18 requires.

## 2026-10-07 — Account security, Phase 4, part two: escalating pauses

### Prompts

1. "How can I test this in a browser"
2. "Ok I tried tripping the message but I do not have a notification of a
   locked account or how many attempts I have left can you add those
   features and notify the user that there account has been locked out.
   Also can you make it tiered so that if after 15 minutes they try to
   use a wrong random password it will increase the time it locks out
   more and more"
3. "add the chat logs to PROMPTS.md if not already"

### Summary

- **Outcome:** Prompt 1 changed no code. It produced a browser
  walkthrough using `customer` (not `admin`, after phase 3's lockout),
  with a Django shell snippet to clear a cooldown, since the admin's
  "clear cooldown" action doesn't arrive until phase 16.

  Prompt 2 reworked the cooldown. The PRD has a dated amendment and
  phase 4 of the plan an amended section with four new criteria:
  - **Escalation.** A pause now lasts a fixed time from the failure that
    started it. After it ends, one more failure starts the next: 15, 30,
    60, then 60 minutes. The ladder restarts after a successful sign-in,
    a cleared cooldown, or 24 hours without a pause. A new
    `SecurityEvent` kind, "Sign-in paused" (`cooldown_started`, migration
    `0005`), records each pause and its length, which is how the ladder
    knows its rung.
  - **The page.** The refusal message is now just "Those details didn't
    work." Below it, the page says "N attempts left before sign-in
    pauses for M minutes" or "Sign-in is paused — try again in N
    minutes". That line comes from `note_refused_sign_in`, which runs the
    same rule against this browser's session history, keyed by an HMAC
    of what was typed. An unknown username counts down exactly as a real
    one does.
  - **The email.** `security.send_alert` and
    `templates/accounts/email/alert.txt` were built early (phase 6 had
    them). `record_failure` sends one alert when a pause starts.
  - **One rule, two histories.** `_standing` and `_pause_earned` are pure
    functions over a list of failures and pauses, so the account (from
    the audit log) and the browser (from the session) can't apply
    different rules. `record_event` gained an `at` argument to pin the
    clock.

  The suite went from 554 to 572 tests. `accounts/test_cooldown.py` was
  rewritten from 21 tests to 39, because the first pause's end and the
  refusal message both changed meaning. Ruff is clean. Nothing was
  committed.

- **Deviations:** the request as worded would have reversed three PRD
  decisions, each with a security cost: real attempt counts would show
  which accounts exist, emails on every failure would let strangers fill
  an inbox, and uncapped escalation would let a stranger lock a customer
  out for as long as they liked. The agent asked rather than built, and
  offered a safer version of each. The user picked all three
  recommendations: a per-browser counter, one email per pause, and
  doubling capped at an hour. One detail differs from how the option was
  worded: it said the ladder resets after "24 hours with no failures",
  but it was built as "no pause started in the last 24 hours", which is
  simpler to compute. With the one-hour cap the two behave almost the
  same.

- **Sideways:**
  - **A known gap, by design.** The page's count can differ from the
    account's when the attempts came from another browser, or when one
    person alternates between their username and their email (the
    browser counts those separately; the account counts them together).
    The account is always the one enforced.
  - **The vocabulary.** The page and the email say "paused", not
    "locked". In the PRD "locked" means an admin has set
    `is_active = False`, which is permanent until undone.
  - **No browser check.** The agent didn't run this in a browser. The
    build summary for prompt 2 ended with an updated five-step
    walkthrough, including running `migrate` for the new event type.
  - **Prompt 3** found every prompt already logged here and in the
    phase 4 entry below. It added itself to the list and changed nothing
    else.

## 2026-10-07 — Account security, Phase 4: sign-in cooldown

### Prompts

1. "@prd/account-security.md @plans/account-security.md Implement phase 4"

### Summary

- **Outcome:** Phase 4 of `plans/account-security.md` was built and its
  seven acceptance criteria ticked:
  - **The rule.** `accounts/security.py` gained `counted_failures()`,
    `cooldown_ends_at()` and `is_cooling_down()`, with docstrings and
    type hints. The count is a query on `SecurityEvent`: wrong passwords
    and wrong two-factor codes in the last 15 minutes, after the latest
    successful sign-in or cleared cooldown. With five or more, the
    cooldown ends when the fifth-newest failure ages out (the oldest,
    when there are exactly five). Each function takes an optional `now`,
    which is how the tests pin the clock.
  - **The backend.** During a cooldown, `UsernameOrEmailBackend` refuses
    without checking the password and without recording a failure. It
    still runs the hasher, so a cooldown takes as long to refuse as a
    wrong password.
  - **The message.** `SignInForm` replaces Django's "Please enter a
    correct username and password" with the PRD's wording. The "15
    minutes" in it is computed from `COOLDOWN_WINDOW`, so the two can't
    drift apart.

  The suite went from 533 to 554 tests (21 new in
  `accounts/test_cooldown.py`). Sixteen failed before the change. The
  other five passed both before and after, because they guard behaviour
  that already held: the cooldown ending, a successful sign-in resetting
  the count, the unknown-identifier row and no mail sent. Ruff is clean.
  Nothing was committed.

- **Deviations:** no recommendations were offered, so none were
  overridden, and no questions were asked. One judgment call changed
  earlier phases' design. **Failed sign-ins are now recorded by the
  backend, not by a `user_login_failed` receiver.** Django sends that
  signal for a cooldown refusal exactly as it does for a wrong password,
  so a receiver couldn't tell which one to record. Checking "is the
  account cooling down?" in the receiver would have nearly worked, but
  an attempt landing as the cooldown ended could be recorded unchecked
  and restart it. The backend is the only place that knows why it said
  no, and every sign-in path, the admin's included, goes through it.
  `accounts/signals.py` now handles only successful sign-ins, and its
  docstring says why.

- **Sideways:**
  - **No time-freezing library.** Neither `freezegun` nor `time-machine`
    is installed, and `SecurityEvent.created_at`'s default holds a direct
    reference to `timezone.now`, so patching it would have had no effect
    on new rows. Rather than add a dependency, the rule's tests pass a
    fixed `now`, and the page-level tests backdate failures by writing
    `created_at`.
  - **The admin's sign-in page** gets the cooldown, because it goes
    through the same backend, but keeps Django's own refusal message. It
    shows that one message for all three cases, so it reveals nothing.
    Restyling the admin's wording wasn't in the phase.
  - **`seed` not run.** It still needs to run before `db.sqlite3` is
    committed, as phase 18 requires.

## 2026-10-07 — Account security, Phase 3: username-or-email sign-in

### Prompts

1. "@prd/account-security.md @plans/account-security.md Implement phase 3"
2. "How can I test this in the browser"
3. "Ok I accidentally locked the admin account out but I did confirm it
   worked can you unlock the account and append the session to
   PROMPTS.md"

### Summary

- **Outcome:** Phase 3 of `plans/account-security.md` was built and its
  four acceptance criteria ticked:
  - **The backend.** A new `accounts/backends.py` holds
    `UsernameOrEmailBackend`, a `ModelBackend` subclass that changes only
    how the account is found. Permissions and the refusal of inactive
    (locked) accounts are inherited unchanged. An unknown account still
    runs the password hasher, as `ModelBackend` does, so it takes as long
    to refuse as a wrong password. The async path goes through the same
    lookup. `AUTHENTICATION_BACKENDS` in `config/settings.py` lists only
    the new backend.
  - **The lookup.** `UserManager.get_by_identifier()` tries the username
    first, then the email, both ignoring case. It reuses `with_email()`,
    so a blank identifier never matches the older accounts that have no
    email.
  - **The form.** `SignInForm` labels the field "Username or email" and
    raises its length limit from 150 (the username limit) to 254 (the
    email limit).
  - **The failed-sign-in log.** `accounts/signals.py` was still looking
    the account up by exact username. A wrong password typed against an
    email would have been logged as an unknown account, and phase 4's
    cooldown, which counts failures per account, would have missed it.
    It now uses `get_by_identifier()`. This wasn't in the plan and was
    found while reading the code.

  The suite went from 511 to 533 tests (22 new in
  `accounts/test_sign_in.py`). Eleven of the new tests failed before the
  change: identifiers by email and by case, the label, the length, the
  settings, the admin sign-in by email, and the failure recorded against
  an email. The other eleven passed both before and after. They cover
  behaviour that must not change: permissions, inactive refusal, wrong
  passwords, and the message a locked account gets matching a wrong
  password's. Ruff is clean. Nothing was committed.

  Prompt 2 changed no code. It produced a browser walkthrough using the
  seeded accounts: a table of identifiers to try, locking `employee` in
  the admin to compare messages, and checking the "Sign-in failed"
  events in the Security events admin.

  Prompt 3: the user locked the `admin` account while following the
  walkthrough (it had said to lock `employee`) and confirmed the generic
  message worked. The agent checked the demo accounts, found only
  `admin` inactive, set `is_active = True` with a single-field update,
  and confirmed `ADMIN@example.com` / `admin123` authenticates. No
  "account unlocked" event was recorded, because that event's recording
  path arrives in phase 16.

- **Deviations:** no recommendations were offered, so none were
  overridden. The only follow-up question was the browser walkthrough.
  Three judgment calls were made without asking. Each was explained in
  the build summary or is visible in the code:
  - **Username first, then email** as two queries, rather than one
    `Q(username) | Q(email)` query. Each step can match at most one
    account, so there's never an ambiguity to resolve.
  - **Widening the field to 254 characters.** The phase didn't ask for
    it, but an email longer than 150 characters couldn't otherwise be
    typed into the box.
  - **Leaving Django's "Please enter a correct username and password"
    message** as it is. Phase 4 replaces it with the PRD's single
    message, so rewording it now would have meant changing it twice.

- **Sideways:**
  - **Formatting.** `ruff format --check` flagged the new test file after
    the full suite passed. It was formatted and its 22 tests re-run.
  - **Ticking the plan's checkboxes** was done with `sed -i` over a line
    range rather than with an edit tool. It changed the four intended
    lines and nothing else.
  - **No browser.** The agent didn't check anything in a browser. The
    user ran the walkthrough and confirmed the locked-account message.
  - **The admin lockout.** The user locked themselves out of `admin` by
    following the walkthrough on the wrong account. There was no other
    superuser to undo it from the admin, so it was fixed from a Django
    shell. A step in the walkthrough telling the user to sign out of the
    admin before testing would have made the mix-up less likely.
  - **`seed` not run.** It still needs to run before `db.sqlite3` is
    committed, as phase 18 requires.

## 2026-10-07 — Account security, Phase 2: email at sign-up and identity rules

### Prompts

1. "@plans/account-security.md @prd/account-security.md Implement phase 2"
2. "How can I check the changes made in the browser"
3. "Append the chat session to PROMPTS.md"

### Summary

- **Outcome:** Phase 2 of `plans/account-security.md` was built and its
  five acceptance criteria ticked:
  - **Sign-up.** `SignupForm` now requires an email. The model field
    stays `blank=True` for older accounts. `clean_email` refuses an email
    another account already uses, in any capitalisation. The "No email"
    docstring was rewritten.
  - **Username rules.** `User.username` is overridden to run a new
    `username_no_at_validator` (in `accounts/validators.py`) alongside
    Django's `UnicodeUsernameValidator`. Because it's on the model field,
    the rule also applies to renames and the admin. Django's
    `UserCreationForm.clean_username` already refuses usernames that
    differ only by case, so it was relied on rather than duplicated.
  - **Constraints.** `User.Meta` gains two functional unique
    constraints: `Lower("username")` and `Lower("email")`, the second
    excluding blank emails. A custom `UserManager.with_email()` does the
    case-insensitive lookup, and a blank email matches nobody.
  - **Emails stored as entered.** `User.clean()` puts back the typed
    email after `AbstractUser.clean()` lowercases its domain, because the
    PRD says emails are stored as entered.
  - **The migration.** `0004_case_insensitive_identities` runs a
    duplicate check before adding the constraints. It groups rows with
    the database's own `LOWER()`, the same expression the constraints
    use. If accounts clash, it raises with every clashing value named and
    changes nothing.

  The suite went from 498 to 511 tests (13 new in
  `accounts/test_identity.py`), all passing on the first run, with ruff
  clean and `makemigrations --check` reporting no drift. The existing
  sign-up tests in `accounts/tests.py` and
  `accounts/test_security_events.py` gained an email field. The dev
  database was migrated, so `db.sqlite3` shows as modified. Nothing was
  committed.

  Prompt 2 changed no code. It produced a browser walkthrough: a table of
  sign-up attempts against the seeded `customer` account (blank email,
  `Customer@Example.com`, `new@person`, `Customer`, and a valid sign-up
  with a mixed-case email), then checking the stored email and the
  "Signed up" event in the admin.

- **Deviations:** no recommendations were offered, so none were
  overridden, and the user asked no questions beyond the browser
  walkthrough. Five judgment calls were made without asking. Each was
  explained in the build summary:
  - **Leaning on Django's own case-insensitive username check** at
    sign-up instead of writing one. The database constraint is the real
    guarantee, and phase 7's rename form will need its own check.
  - **A separate `@` validator** with its own message, kept alongside
    Django's validator rather than replacing it with a narrower regex, so
    the error tells the user why `@` is refused.
  - **Overriding `User.clean()`** to keep the email's domain as typed.
    Django's default would have stored `Casey@example.com` for
    `Casey@Example.com`.
  - **Testing the migration for real.** The tests roll accounts back to
    0003 with `MigrationExecutor`, insert duplicates through the
    historical model, migrate forward and restore the schema afterwards.
    This needs a transactional database and adds a few seconds, but it
    tests the actual migration rather than a copy of its function.
  - **Ticking the plan's checkboxes**, following what the phase 1 commit
    did.

  One gap was flagged rather than fixed: the admin has no form-level
  email check yet, so a duplicate entered there shows the constraint's
  message as a form-wide error. Phase 17 covers admin edits.

- **Sideways:**
  - **A failed source lookup.** The first attempt to locate Django's
    auth source ran `python -c "import django.contrib.auth.forms"`
    outside Django's settings and crashed with `ImproperlyConfigured`.
    The traceback still printed the path, and the source was grepped
    directly from `.venv` instead.
  - **A loose test, tightened before it ran.** The model-validation test
    was first written with `pytest.raises(Exception, ...)` and narrowed
    to `ValidationError` before the first run.
  - **Line endings.** Adding the email to the existing tests with `sed`
    produced Git's LF-to-CRLF warnings. They are harmless.
  - **`PROMPTS.md` at the end of the build.** The build summary said the
    log had been left alone "since that log looks like your own
    write-up." The real reason is this file's rule that entries are added
    only when asked, which prompt 3 then did.
  - **No browser.** The agent didn't check anything in a browser. The
    walkthrough in prompt 2 is untested by the agent, and the
    migration's duplicate check can only be seen through the tests.
  - **`seed` not run.** It still needs to run before `db.sqlite3` is
    committed, as phase 18 requires.

## 2026-10-07 — Account security, Phase 1: the audit log tracer

### Prompts

1. "@prd/account-security.md @plans/account-security.md Implement phase 1"
2. "How can I manually verify this phase in the browser?"
3. "I have this error when starting the server You have 1 unapplied
   migration(s). Your project may not work properly until you apply the
   migrations for app(s): accounts. Run 'python manage.py migrate' to
   apply them."
4. "add the session to PROMPTS.md"

### Summary

- **Outcome:** Phase 1 of `plans/account-security.md` was built and its
  seven acceptance criteria ticked:
  - **The model.** `accounts.SecurityEvent` (migration
    `0003_securityevent`) records the affected `user` and the `actor`,
    both `SET_NULL`. Each row also keeps a username snapshot, the event
    type, a `created_at` that tests can pin, the IP and a JSON `details`
    field.
  - **The deep module.** `accounts/security.py` is the fourth deep
    module. It holds `record_event`, and `client_ip`, which reads
    `REMOTE_ADDR` only and stores anything that isn't a valid address as
    unknown.
  - **What gets recorded.** `SignupView.form_valid` records sign-ups.
    Sign-ins are recorded by receivers on Django's `user_logged_in` and
    `user_login_failed` signals in `accounts/signals.py`, so `/admin/`
    sign-ins are logged too. A failed attempt is attached to the account
    it named. An unknown identifier is stored with no user and no
    identifier, only the IP.
  - **The admin.** `SecurityEventAdmin` is read-only for everyone and
    visible to superusers only, even when a staff member holds
    `view_securityevent`. It filters by kind, date, actor and user and
    searches by username snapshot.
  - **The seed.** It clears the demo accounts' events on each wipe and
    gives all 12 seeded users a sign-up event.

  The suite went from 476 to 498 tests (22 new in
  `accounts/test_security_events.py`), all passing, with ruff clean.
  Nothing was committed.

  Prompt 2 changed no code. It produced a browser walkthrough: the
  seed's 12 sign-up events, a table of storefront actions and the row
  each should add, deleting a throwaway account to see its events
  survive, the 403s on add, change and delete, and the staff check
  including an explicitly granted view permission. Prompt 3 applied the
  pending migration.

- **Deviations:** no recommendations were offered, so none were
  overridden. Four judgment calls were made without asking. The first
  three were flagged in the build summary; the fourth wasn't:
  - **Signals, not `SignInView`,** for sign-in events, so no sign-in
    path can skip the log.
  - **All 20 event types defined now** from the PRD's list, rather than
    one migration per phase.
  - **`actor` stored exactly as passed:** the owner for their own
    actions, the admin for overrides, `None` for failed sign-ins and
    server commands. Phase 5's "by ThoughtTronix support" depends on it.
  - **The seed deletes audit rows.** That sits awkwardly with a
    "tamper-proof" log. It is confined to the seed's own accounts and
    explained in a comment: without it, every reseed would leave
    another set of rows from the deleted accounts behind.

  For now, failed sign-ins are matched by exact username. Phase 3
  replaces this with the case-insensitive username-or-email lookup. The
  user's follow-ups were prompts 2 and 3.

- **Sideways:**
  - **The dev database wasn't migrated during the build.** The summary
    told the user to run `migrate` and the walkthrough listed it under
    setup, but the server was started without it and printed the
    unapplied-migration warning. It was applied in prompt 3. `seed` was
    deliberately not run for the user, because it wipes the demo world;
    it is still needed before the walkthrough's step 1 and before
    `db.sqlite3` is committed.
  - **Test runs.** Every test passed on its first run. `ruff format`
    reformatted three new files afterwards (formatting only). Tests were
    run with `uv run python -m pytest`, because of the Windows launcher
    block recorded on 2026-10-03.
  - **A miscount.** The build summary told the user "20 new" tests.
    Recounting with `--collect-only` while writing this entry found 22,
    because the parametrised IP test counts as three.
  - **No browser.** Nothing was checked in a browser by the agent. The
    admin's read-only pages and 403s were verified through the test
    client only.

## 2026-10-07 — Account management and security: the PRD broken into an 18-phase plan

### Prompts

1. The `/prd-to-plan` skill, given: "@prd/account-security.md create a
   plan from the PRD and place it in the plans folder, also append this
   session to the PROMPTS.md section."
2. "Keep 18 phases (Recommended)" (asked whether the granularity felt
   right. The alternatives were merging to about 12 or splitting
   further.)

### Summary

- **Outcome:** `plans/account-security.md`, with no code. The header holds
  the durable decisions: everything in `accounts`, `accounts/security.py`
  as the fourth deep module, the PRD's full URL table, the new models and
  their FKs (`SecurityEvent` with `SET_NULL` and a username snapshot), the
  username-or-email backend, and the superuser-only admin. The 18 phases
  are thin vertical slices. The audit log goes first because the cooldown,
  the activity card and "password last changed" are all derived from it.
  Next come email and identity, sign-in, the cooldown and the Account hub.
  After that the self-service changes, with the session key, re-auth and
  alert helper built once in the change-password phase. Two-factor follows
  in three slices: enrol, two-step sign-in, manage. Then the superuser
  gate, admin in three slices, and finally break-glass, settings and docs.
  Every one of the PRD's 54 user stories is assigned to a phase.

- **Deviations:** none. The proposed breakdown was accepted as offered.
  Two orderings were my calls and weren't put to the user. Two-factor
  enrolment comes before two-step sign-in, so for one phase a user can
  enrol without it being enforced. Admin overrides come after the
  superuser gate, so the admin is already protected by two-factor by the
  time the overrides exist.

- **Sideways:** the PRD cites `prd/account-security-decisions.md` (the
  Q1–Q22 interview record) and yesterday's log entry says it was written,
  but the file isn't in the working tree or anywhere in git history. The
  plan was built from the PRD alone, which restates every decision it
  needs. The decisions file should be recovered or the PRD's reference
  corrected before the build.

## 2026-10-06 — Account management and security: a 22-question design interview, recorded and not built

### Prompts

1. The `/grill-me` skill, given: "ThoughtTronix is in need of an account
   management and security system. The current website allows users to
   log in with their email and password as well as sign up for an
   account. Currently, however, there is no way for users to edit
   sections of their account, which would include their email and
   password, as well as any way for a user to change their password or
   username. or email. Please create a design outline using the grill me
   skill. Do not implement any of the changes; only record the outcome of
   our conversation, as that will come later. Please ensure the
   following: Features are operable and refined upon as necessary: Allow
   users to provide an email address when creating an account. Ability to
   change their password. Ability to reset a forgotten password. 2FA
   integration using an external application such as Google
   Authenticator, allowing users to authenticate offline. Ability to
   change their username and email. Admins must also be able to view and
   monitor these changes and override them if necessary. Please add any
   additional security features you feel might be beneficial that would
   not add too much to the initial'design."
2. "3" (Q1, sign-in identifier: username or email)
3. "1" (Q2, email required at sign-up)
4. "2. But for testing purposes can you add the ability for admins to
   override this and verify their email, I do not intend on implementing
   email API services into this application to send to a real email."
   (Q3, soft verification)
5. "1" (Q4, superusers only hold override powers)
6. "1. Sounds good but can you make an accesible link for admins to click
   on in their profile manager and in the back office it should only be
   available to admins(superusers)" (Q5, admin tools in `/admin/`)
7. "1" (Q6, Account hub with one page per change)
8. "1. Also if possible can we give the users who have 2FA active the
   ability to use that instead to verify themselves." (Q7, current
   password on sensitive forms)
9. "1" (Q8, `pyotp` + `segno` with own models)
10. "1" (Q9, hashed recovery codes plus admin reset)
11. "1" (Q10, two-step sign-in, code every time)
12. "1" (Q11, confirm the new email by link before switching)
13. "1" (Q12, renames any time, logged)
14. "1" (Q13, reset links to any email on the account)
15. "Lets go with option 1, and yes a securtity card would be nice to add
    as well with the criteria you mentioned" (Q14, `SecurityEvent`
    model and the activity card)
16. "1" (Q15, 5-in-15-minutes cooldown from the audit log)
17. "2" (Q16, 2FA mandatory for superusers)
18. "2" (Q17, seeded admin forced through setup, not pre-enrolled)
19. "1" (Q18, set-password form plus send-reset-link action)
20. "1" (Q19, alert emails for high-risk events)
21. "1" (Q20, TOTP secret stored plain, run `seed` before committing)
22. "1" (Q21, cookie hardening and "sign out other devices" in)
23. "1 and make sure that the chat logs are recorded in PROMPTS.md"
    (Q22, record as `prd/account-security-decisions.md`)

### Summary

- **Outcome:** 22 questions, no code. The decisions are recorded in
  `prd/account-security-decisions.md`, grouped by feature, with a
  deferred list and five open points for the PRD stage. The headline:
  username-or-email sign-in; required, unique, softly verified email;
  an `/accounts/` hub with one page per change, each guarded by the
  current password or a 2FA code; TOTP via `pyotp` + `segno` in a new
  fourth deep module, `accounts/security.py`, with hashed recovery codes
  and 2FA mandatory for superusers; a read-only `SecurityEvent` audit
  log in `/admin/` that also drives a 5-in-15-minutes sign-in cooldown,
  the user's activity card and a short list of alert emails; and
  superuser-only overrides in `/admin/` that never touch another
  superuser. Nothing in the repo besides this log and the new decision
  file was touched.

- **Deviations:** one recommendation overridden. Q17: the user chose to
  have the seeded `admin` go through forced 2FA setup on first sign-in
  after every `seed`, instead of a pre-enrolled, documented demo secret.
  Three answers added requirements: Q3 added an admin "Mark email
  verified" override, because real email delivery won't be built; Q5
  added a superuser-only "User security" link on the Account page and in
  the back-office nav; Q7 let 2FA users re-authenticate with a code
  instead of their password. Two recommended points were accepted
  without comment and are flagged for confirmation at the PRD stage:
  the Q4 guardrail (no overrides on yourself or another superuser) and
  the Q7 exception (turning 2FA off needs both password and code).

- **Sideways:** the brief said users "log in with their email and
  password", but the code and the core PRD say username-only, with no
  email at sign-up. Reading `accounts/forms.py` before the first question
  caught it, and Q1 became a real choice instead of an assumption.
  Grepping for `username` before Q12 found that Django's default
  username validator allows `@`, which would have made username-or-email
  sign-in ambiguous; banning `@` and enforcing case-insensitive
  uniqueness were added as fixed rules. Q20 found that committing
  `db.sqlite3` for grading would permanently put any real TOTP secret
  into git history, which led to the "run `seed` before committing" rule.

## 2026-10-03 — Image sizing and product-page polish: the build, a blurred fill with full-size view, and two alignment passes

### Prompts

1. "@HANDOFF.md implement the feature"
2. "On final design decsion and then i think it wuld look perfect for smaller
   images that are cutoff at the sides, can we add a blur effect to make up
   the lost side of the image it should still be cropped, but as soon as the
   user clicks on the image it will alow them to view it in full detail"
3. "One last change the image in the the actual product is a little too high
   ideally I would like it to be centered with the product text as to make
   the design look as cohesive as possible."
4. "Ok for items that have multiple imges can we also have them line up as
   well to where the top of the fram is close in line with the top of the
   title fram the image should not go above the product title"
5. "can you append the list of change to the PROMPTS.md file"

### Summary

- **Outcome:** The design in `HANDOFF.md` was built as specified:
  - **4:3 frames everywhere.** Catalog cards, the back-office list, the
    Images page, the remove-image confirmation and the image picker all
    use 4:3. The shared line-item thumbnail is now 64×48 and still sizes
    its own `<img>`.
  - **One CSS-only gallery on the product page.** It has a hidden radio
    per image with the main image first, a three-wide scroll-snap
    thumbnail strip, wrap-around ❮ ❯ arrows and an "n / total" badge.
    A product with one image gets the plain frame, with no radios, strip
    or arrows.
  - **Product-page layout.** The breadcrumb is a shaded bar with grid and
    tag icons. The text column sits `md:gap-16` away in its own padded
    card.
  - **Back-office list.** "No image" is replaced by a faded category
    placeholder with the tooltip "No photo yet — manage images".

  The gallery needs one exception to "Tailwind classes only": pairing
  radio N with slide N and thumbnail N can't be written as classes,
  because the numbers change per product. Eighteen short state rules in
  `assets/css/source.css` cover nine positions (`MAX_IMAGES`), and the
  exception is recorded in `docs/TEMPLATES.md`. Two new partials keep the
  "main image, then extras" loops short: `_gallery_slide.html` and
  `_gallery_thumb.html`.

  Prompt 2 added `_zoom_frame.html`. A blurred, cropped copy of each
  product-page photo fills the empty sides of the letterboxed frame,
  drawn through `_picture.html` with a new `decorative` flag that empties
  the alt and hides the copy from screen readers. Clicking the photo
  opens a full-size `:target` overlay (`#zoom-<n>`). It closes on
  `#close`, a fragment no element has, so the page doesn't jump.
  Placeholders get neither the blur nor the overlay.

  Prompts 3 and 4 settled the alignment on md+ screens. The text card
  sits at the top of the row (`md:self-start`) and the image column
  centres in the row (`md:self-center`). When the text is taller, the
  image is centred on it; when the gallery is taller, the two tops line
  up. The image never rises above the title.

  `docs/IMAGES.md`, `docs/TEMPLATES.md` and the `extra_pictures` and
  `ProductImage` docstrings were updated. `extra_pictures` behaves exactly
  as before. The suite grew from 433 to 436 tests, all passing, with ruff
  clean and the CSS rebuilt.

- **Deviations:**
  - **Prompt 2's scope was decided, not asked.** The request was read as
    the product page only, the one place with letterboxing. Catalog cards
    already crop to fill, and clicking one already opens the product
    page. "Full detail" was read as a full-size overlay rather than
    opening the image file in a new tab.
  - **The handoff's PROMPTS.md step was held back.** This log's own rule
    says entries are added only on request, so the build's entry waited
    for prompt 5.
  - **Changes were offered back for some limits rather than worked
    around:**
    - The strip's thumbnails load the 1200 px display files, because
      `extra_pictures` only provides those and the handoff said not to
      change it.
    - Esc doesn't close the full-size view.
    - The browser's Back button reopens the last full-size view.
    - "Full detail" tops out at 1200 px, since the original upload isn't
      kept.

- **Sideways:**
  - **`uv run pytest` was blocked** by a Windows Application Control
    policy on the `pytest.exe` launcher. Every run since has used
    `uv run python -m pytest`.
  - **The first Tailwind build reported "up to date"** and rebuilt
    nothing. A grep of the compiled CSS confirmed the new classes were
    already there, presumably from a running watcher, and later builds
    used `--force`.
  - **A real bug, caught by a test.** The full-size overlay's `<img>`
    inherited `eager=True` from the surrounding include, so it would
    have loaded with the page. The test asserting it was lazy failed,
    and `eager=False` is now passed explicitly.
  - **Prompt 3's fix caused prompt 4's problem.** Centring the two columns
    on each other moved a multi-image gallery, which is taller than the
    card because of its strip, above the title. That case wasn't flagged
    when prompt 3 was answered. The final layout replaced the symmetric
    centring with the asymmetric rule above.
  - **Nothing was checked in a browser.** Every change was verified by
    tests and by grepping the compiled stylesheet, not visually.

---

## 2026-10-03 — Image sizing and product-page polish: the design interview and the handoff

### Prompts

1. The `/grill-me` skill, given the changes in the user's own words:
   "Currently the images and menu look a little strange and I would like to
   have them adjusted to look better. Firstly the top navigation menu per
   product has a menu that allows a person to navigate back to the catalog of
   view the associated category of the product, can this menu look nicer have
   spacing and styling along the top of the product. Next the images for the
   product and the catalog are just too big and have no real sizing
   constraints, I would like to have all tiles pretty much the same size as
   the placeholder images, cropping or clipping an image is acceptable. Next
   the product description of an image does not look quite right either, The
   text is right adjacent to the actual image can we have some additional
   padding inbetween the text and the image. Nex the carousel feature is not
   working as fully intended, I do not want to have images appended in an
   ever expanding vertical list I would like to have them in a horizontal
   list where at most it would have about 3 images and it would allow you to
   scroll between them, it would show the tumbnail image at the bottom as you
   are scrolling and update the main image to display what the thumbnail
   image is showing. Next in the back office menu instead of showing no image
   can you place the placeholder image"
2. "4:3 everywhere (Recommended)" (Q1: frame shape for catalog, product page
   and back office)
3. "Yes, make them 4:3 (Recommended)" (Q2: line-item thumbnails become
   64×48)
4. "Show whole photo (Recommended)" (Q3: product page main frame letterboxes
   rather than crops)
5. "One gallery, main first (Recommended)" (Q4: main image is the first
   thumbnail; the separate "More images" carousel goes)
6. "CSS-only radio trick (Recommended)" (Q5: how a thumbnail swaps the main
   image without JavaScript)
7. "Scroll strip + arrows on main (Recommended)" (Q6: three visible
   thumbnails, wrapping arrows on the main image)
8. "Styled breadcrumb bar (Recommended)" (Q7: the top navigation)
9. "Wider gap + text panel (Recommended)" (Q8: space between the gallery and
   the text)
10. "Placeholder, dimmed + tooltip (Recommended)" (Q9: back-office list rows
    without a photo)
11. The `/handoff` skill, with no arguments.
12. "Please append a list of change to the PROMPTS.md file according to its
    formatting"

### Summary

- **Outcome:** Design only; no application code was written. Nine
  questions, one at a time, each naming what it settled and recommending an
  option. The agreed design, the tests and docs it will touch, and the
  gotchas are recorded in `HANDOFF.md`, which was newly created. In brief:
  every product image frame becomes 4:3 to match the placeholders, including
  the shared line-item thumbnail; the product page gets one CSS-only gallery
  (hidden radios, main image first, a three-wide scrolling strip, wrapping
  arrows) in a fixed letterboxed frame; the breadcrumb becomes a padded,
  shaded bar with icons; the text column moves 4rem away into its own card;
  and the back-office list shows a faded placeholder with a tooltip instead
  of "No image".

  Several answers came from reading rather than asking: the catalog cards
  use a 4:5 frame while the placeholder SVGs are 4:3, which explains why
  placeholders look smaller than photos; the product page's main image is
  `h-auto w-full` with no height bound; the back office's "No image" is a
  single `has_image` branch that `_picture.html` already makes unnecessary;
  `docs/TEMPLATES.md` forbids JavaScript beyond HTMX, which shaped Q5 and
  Q6; and four tests in `products/test_image_views.py` assert the old markup
  and will need rewriting.

- **Deviations:** None from a recommendation; every answer took the
  recommended option. Two answers reverse earlier settled decisions, at the
  user's request: Q1 replaces the 2026-09-30 interview's Q9 (a fixed 4:5
  card frame) and that session's 48×60 thumbnail, and Q4 returns to roughly
  the original Q10 layout (main image first with a thumbnail row), undoing
  the main-image-only page with a separate extras carousel from the
  2026-09-30 build's prompt 5. No follow-up questions were asked.

- **Sideways:** No code, so nothing broke. One limitation was accepted
  knowingly rather than discovered: without JavaScript, the arrows on the
  main image cannot scroll the thumbnail strip along, so past the third
  image the highlighted thumbnail can sit out of view. The "too big" complaint
  was diagnosed from the templates and the compiled stylesheet (which does
  contain the aspect-ratio classes), not from a screenshot or a live
  browser, so the cause has not been confirmed visually.

---

## 2026-09-30 — One fixed size for cart, checkout and order thumbnails

### Prompts

1. "@HANDOFF.md everything seems to be working correctly but there are some
   additional stlying implementation changes I would like to make. When I
   tems are added to cart the image is huge and overlaps the price of the
   item, the same can be said on the checkout and orders section, can we
   make the thumbnail images on all of these one specific size and make sure
   it does not overlap any text"
2. "These images are still not sized correctly and are overlapping text, can
   you please make sure these images are one specific size and that they do
   not overlap or make the text look weird", with three screenshots: the
   cart, checkout's "Your order" box and the order confirmation, each showing
   a roughly 600 px photo over the text.
3. "Ok can you append this conversation to PROMPTS.md with the styling
   specified there"

### Summary

- **Outcome:** Every line-item thumbnail now renders through one partial,
  `products/partials/_thumbnail.html`, as a fixed 48×60 (4:5) frame. It is
  used on the cart, checkout, order history, order detail, confirmation and
  back-office order detail. Before, each page set its own width (32–56 px).
  The partial takes `pic`, an optional `href` (the cart links to the
  product) and `tooltip` (history and confirmation), and is included with
  `only`, so page context such as a `title` cannot leak in.
  `products/partials/_picture.html` gained optional `width`/`height`
  overrides for the `<img>` attributes; the catalog and product page are
  unchanged. In the cart and checkout the text beside the thumbnail got
  `min-w-0` so long names wrap next to the image instead of under or over
  it. `docs/TEMPLATES.md` records the partial and why it is built this way.
  Result: 431 tests passing, ruff clean, CSS rebuilt. Nothing committed.

- **Deviations:** None from a recommendation. The user chose no size; 48×60
  was picked to fit four thumbnails in an order-history row, and 64×80 was
  offered as a one-line change. A dev-mode cache-busting fix for the
  stylesheet was offered and is unanswered.

- **Sideways:** The first fix did not fix the user's browser, and the cause
  was misread at first.
  - **Prompt 1.** A render through the test client, screenshotted with
    headless Edge, showed thumbnails already the right size before any
    change. The session guessed a stale cached `tailwind.css`, told the user
    to press Ctrl+F5, and added the shared partial with `width="48"
    height="60"` on the `<img>` as a fallback. It checked that fallback only
    with *no* stylesheet at all, which is not the failure the user had.
  - **Prompt 2.** The user's screenshots showed the photos still at full
    size. Logging in to the live dev server with curl proved it was serving
    the new markup and a current stylesheet, so the browser's cached CSS was
    confirmed as the cause: the tag links a plain `/static/css/tailwind.css`
    with no version in `DEBUG`. That old copy had `w-full`/`h-full` but not
    the frame's `w-12`/`h-15`, so `w-full` of an unsized frame resolved to
    the photo's natural 600 px and overrode the width attribute. The fix
    sizes the `<img>` itself (`h-15 w-12 max-w-none`) instead of as a
    percentage of its frame. It was verified against a copy of the
    stylesheet with those rules deleted, which reproduces the user's state.
  - **Side effects.** The render script added products to the demo
    `customer` account's cart on every run, leaving 13 items in the dev
    database; the user was told `seed` resets it. Several stale `runserver`
    and `tailwind watch` processes from earlier sessions were found running,
    only one of them serving port 8000.

---

## 2026-09-30 — Product images: the build, then two rounds of back-office and gallery changes

### Prompts

1. "@HANDOFF.md Implement this feature"
2. "Code only (Recommended)" — the answer to the question `HANDOFF.md` said
   to ask first: whether to write `prd/product-images.md` and
   `plans/product-images.md` before coding.
3. "Ok now that you have implemented the features how can I manually review
   and test the code that you generated?"
4. "Ok I have some problems when I try to adda product, firstly I dont know
   what "slug" is, I would simply like to have the image uploaded using a
   simple upload button and if more than one image is added show it as a
   gallery as discussed before. Next the tags section looks off with all of
   the text being scrunched togehter can be make this a simle list view where
   I can select by using checkboxes for which tags I would like to add"
5. "Ok there are a few things I would like to change first of all cn we make
   the upload images instead of having it say Choose make it an upload button
   and specify that to set a main image first add all images, then on the
   product options have the option for the user to actually select the main
   image after they have all loaded and are able to be previewed. The next
   thing I notice that needed to be changed is the way the images are listed
   on the given product pages. Right now it has the images loaded twice, it
   merges the main and secondary images into the primary image rather than
   just using the main image only. Also there does not seem to be any
   scrollable carousel for viewing the secondary images just a line of
   images"
6. "Ok can you append this conversation to PROMPTS.md using the styling
   provided on PROMPTS.md"

### Summary

- **Outcome:** The design in `HANDOFF.md` was built as agreed, then reshaped
  twice by the user's own testing.

  *The build (prompts 1–2).* `products/images.py` became the third deep
  module. It holds one validator with the seven rules, each refusal naming
  the file and the values it found. It also holds the pipeline (resize to
  display and thumbnail WebPs in memory, write under random names, save in a
  transaction, delete old files on commit), the extras' ordering, and
  `snapshot_for_order`. `Product` gained the main image fields,
  `ProductImage` holds up to eight extras, and `OrderItem` gained a snapshot.
  Templates only ever render a `Picture` through
  `products/partials/_picture.html`. `card_image`, `display_image` and
  `OrderItem.thumbnail` return the media URL only when the file exists, and
  the category placeholder otherwise. `place_order` copies thumbnails in
  `on_commit(robust=True)`, so a failed copy cannot fail or roll back an
  order. Other pieces:
  - a staff-only Images page;
  - read-only previews in the Django admin;
  - `SERVE_MEDIA` independent of `DEBUG`, and `MEDIA_ROOT`, both in
    `.env.example`;
  - a temporary `MEDIA_ROOT` for every test;
  - thumbnails on the cart, checkout and all order pages, loaded without
    N+1 queries via `Order.objects.with_items()`.

  The 13 baseline photos moved to `products/seed_images/` under slug names,
  with written alt text, and `product-images/` was deleted after a checksum
  comparison. The seeded catalog went from 27 MB of PNGs to about 4 MB of
  WebPs, and reseeding leaves no stray files. `CLAUDE.md` now says "three"
  deep modules, and `docs/IMAGES.md` was added. Result: 401 tests (86 new),
  ruff clean, and the catalog and carousel checked by headless-Edge
  screenshot.

  *Prompt 3* changed no code. It produced a manual review and test script: a
  file-by-file reading order, a browser walkthrough for each login, a Python
  snippet that generates one bad file per validation rule with the expected
  message for each, and steps for the missing-file, product-deletion and
  `DEBUG=False` checks.

  *Prompt 4.* `Product.save` now generates the slug from the name, numbered
  if taken (`seraphine-2`), and never changes it on rename. The field left
  the form and became `blank=True` (migration `0005`). The product form
  gained a multi-file upload: the first file fills the main image and the
  rest become extras. Tags became a checkbox list, one choice per row. To
  keep the brief's "never accept a file and then lose it" once uploads sat on
  a form with other fields, images that pass validation are *held* under
  `media/pending/` and carried as hidden tokens while the employee fixes
  other errors. Stale holds are swept after a day. Result: 412 tests.

  *Prompt 5.* The upload became an **⬆ Upload images** button that sends
  files over HTMX to `StageProductImagesView` the moment they are chosen.
  That view returns `_image_picker.html`: a preview per image, a "main image"
  radio button, and a ✕ to discard. On the edit form the product's saved
  images are choices too. `attach_uploads` applies the choice through a new
  `make_main`, which swaps stored names rather than files, and the Images
  page gained a "Make main image" button. The product page now shows the
  main image once, with the extras in their own "More images" carousel with
  wrapping ❮ ❯ arrows and a counter. The old thumbnail row, which repeated
  the main image, is gone. Result: 431 tests passing, ruff clean. Nothing
  has been committed.

- **Deviations:** Prompt 2 took the recommended option. Prompts 4 and 5
  reversed three settled decisions from the design interview, each at the
  user's request:
  - **Uploads on the product form.** The interview had put uploads on a
    separate Images page, so that an error elsewhere on a form could never
    discard a chosen file. Uploads now sit on the product form, and holding
    accepted images is what preserves that guarantee. The Images page stays
    for managing saved images.
  - **Promoting an extra to main.** "No promote extra to main" became
    allowed, but only by an explicit choice; removing the main image still
    leaves the placeholder, not the first extra.
  - **The gallery.** The Q10 layout (main image first in the carousel, plus
    a thumbnail row) became main-image-only with a separate extras
    carousel.

  "Create product redirects to the Images page" was also dropped once images
  could be added on the form itself. Two things were offered and are still
  unanswered: making the category and tag slugs automatic as well, and
  replacing the anchor-link carousel if its page nudge on arrow clicks
  bothers the user. `HANDOFF.md` asked the build session to write an entry
  here. It was declined, because this file's own rule allows entries only
  when the user asks. This entry is the one that prompt asked for.

- **Sideways:** Several defects were caught during the work, most of them by
  tests:
  - **PNG decoding before the size checks.** A new megapixel test failed
    with "image file is truncated", which exposed a real hole. On a PNG,
    Pillow's `getexif()` decodes every pixel, and it ran *before* the
    decompression-bomb check. Orientation is now read from the header chunks
    only.
  - **A partial as an on-commit callback.** A test of a crashing snapshot
    step showed that Django's `robust=True` error logging reads
    `func.__qualname__`, which `functools.partial` lacks. A failed snapshot
    would have crashed the logger itself. It is now a lambda, and
    `docs/IMAGES.md` records why.
  - **An import ruff removed.** `ruff --fix` dropped `reverse` from
    `products/views.py` when it was briefly unused. It was needed again in
    prompt 5, and 19 tests failed with `NameError` until it was restored.
  - **Tags still inline.** The first tag fix still rendered inline, because
    DaisyUI's `.label` is `inline-flex`. A screenshot caught it, not a test.
  - **Bad tests.** Two tests written in prompt 5 were vacuous: one assertion
    ended in `or True`, and one compared against a field `make_main` had
    already blanked. Two others depended on exact whitespace. All four were
    rewritten before the run, with a regex helper for the checked radio.
  - **Smaller slips.** A test missed that Django escapes apostrophes in
    messages. The media URL pattern first had a leading slash (Django warning
    `urls.W002`). A race in `move_extra` (an extra deleted mid-move raising
    `StopIteration`) was found on self-review and closed.

  Visual checking was limited. Headless Edge could not sign in, so the
  back-office screens were rendered through Django's test client with
  asset URLs pointed at a running dev server. Three blank or half-scrolled
  captures turned out to be lazy loading and smooth-scroll timing, not bugs,
  confirmed by checking every image URL returned 200 and re-shooting the
  public page live. The HTMX upload and the carousel arrows have therefore
  not been clicked in a real browser. `/security-review` and `/code-review`
  were recommended and not run.

## 2026-09-30 — Product images: the design interview and the handoff

### Prompts

1. The `/grill-me` skill, given the feature in the user's own words:
   "Currently there are no images on the catalog, and only a placeholder is
   shown for each item. This has allegedly reduced sales for products, as
   they do not have an idea as to what the product looks like. Some
   additional criteria for this image implementation are that a set of
   baseline images should be used; these images are located in a temporary
   folder called product-images. Pages should remain fast and responsive.
   The following has been mentioned as non-negotiable: Every product must
   display either its intended image or an existing placeholder. Missing
   files or broken images should not be loaded or attempted to be loaded.
   Employees must also be able to upload images through the back office; if
   an image file is unsuitable, reject the image and explain to the employee
   why the image cannot be used in clear/understandable language. Also do
   not accept the file first and then lose it."
2. "A" (Q1: `ImageField` under `MEDIA_ROOT`)
3. "Can we go with B but add some additional prameters, by default a
   product should only get one image but, we should also add the ability to
   potentially add more than one if we so choose. This should not affect
   the main image but still allow you to view the other images if there are
   more than one" (Q2: one image vs. gallery)
4. "A" (Q3: `Product.image` plus a separate `ProductImage` for extras)
5. "B" (Q4: resize at upload to two WebPs, discard the original)
6. "D" (Q5: render-time existence check plus disk/DB sync)
7. "A" (Q6: the seven validation rules and their messages)
8. "A" (Q7: a separate per-product Images page)
9. "lets go with A for both" (Q8a SyncRest clean main + poster extra;
   Q8b SoulSear image on Mark I only)
10. "A" (Q9: fixed 4:5 card frame, cropped to fit)
11. "A" (Q10: CSS carousel with thumbnail row)
12. "A" (Q11: all seven Images-page actions, 8-extra limit)
13. "A" (Q12: optional alt text with fallbacks)
14. "B" (Q13: `SERVE_MEDIA` setting, on by default)
15. "C" (Q14: images on cart, checkout *and* order pages)
16. "B" (Q14b: snapshot the thumbnail onto `OrderItem` at purchase)
17. "A" (Q15: images read-only in Django admin)
18. "A" (Q16: third deep module, `products/images.py`)
19. The `/handoff` skill: "the next session implements the design we just
    agreed"
20. "Ok using the PROMPTS.md write a session log using the standard prompt
    listed there"

### Summary

- **Outcome:** Design only; no application code was written. Seventeen
  questions (Q1–Q16 plus a Q14b sub-question), one at a time, each naming
  what it settled and recommending an option. The agreed design is recorded
  in `HANDOFF.md` and nowhere else yet. In brief: a main image on
  `Product.image` and up to eight ordered extras in `ProductImage`; every
  upload validated by seven plain-language rules and re-encoded to a
  display and thumbnail WebP; templates only ever ask a model property that
  returns the file's URL if it exists on disk, else the category
  placeholder; uploads live on a dedicated Images page so an unrelated
  form error can't discard them; order lines snapshot their thumbnail in
  `place_order`, where a failed copy must never fail the order; and the
  pipeline becomes a third deep module, `products/images.py`, with
  CLAUDE.md to be amended to say so.

  Several decisions came from reading rather than asking: the baseline
  PNGs are ~2 MB each (about 25 MB for a catalog page served raw); the
  placeholders are 4:3 while 12 of 13 photos are ~4:5; `docs/TEMPLATES.md`
  forbids JavaScript beyond HTMX, which ruled out gallery libraries;
  `ProductAdmin` restricts no fields, so the new `ImageField` would have
  appeared in `/admin/` as an unvalidated back door; Django stops serving
  media when `DEBUG=False`, which would have produced exactly the broken
  images the brief forbids, and the render-time file check can't catch it;
  CLAUDE.md's "exactly two deep modules" rule meant Q16 had to be asked
  rather than drifted past; and the seed builds its demo orders directly,
  not through `place_order`, so snapshots there need their own step. The
  two ambiguous baseline images were settled by looking at them and
  checking seed descriptions — Mark I's "took several things off it"
  matched a ruined skyline, and Tactical Core's tagline is literally
  "without the skyline".

- **Deviations:** two recommendations were overridden, and both widened the
  design. Q2: I recommended one image per product; the user chose a gallery
  constrained to one main image plus optional extras that never affect it.
  That reshaped Q3 (hybrid model), and created Q10 (the carousel) and most
  of Q11 (the extras actions and limit). Q14: I recommended stopping images
  at the cart and checkout; the user chose order pages too. That forced
  Q14b, because `OrderItem` only links to the *current* product and would
  have shown today's image on months-old orders; it was settled as a
  snapshot, which touches `place_order`. One answer was read more broadly
  than given — "A" to Q1 was taken to also approve moving the baseline
  images into a committed folder, and the user was told so. One question
  was left unanswered: whether to write `prd/` and `plans/` documents
  before coding. `HANDOFF.md` tells the next session to ask it first.

- **Sideways:** no code, so nothing broke, but the interview contained
  counting errors of mine. Q8 said "eleven of the 13 files match exactly
  one product" above a table of ten; the true split was ten unambiguous,
  one ambiguous (SoulSear) and two for one product (SyncRest). Q12 said the
  seed had 14 images; it has 13 across 12 products. That one was caught and
  corrected at the start of the next reply. The Q8 miscount was not caught
  until this log. Q1's "about 21 products keep the placeholder" became 22
  once the mapping was settled.

## 2026-09-22 — Discount codes: the design interview, the build, and the review

*Session ran 21–22 September and is logged on the 22nd. This is the session
that created the discount feature; the other 2026-09-22 entry further down is
the separate follow-up session that added usage limits, multi-product scope
and reinstatement on top of it.*

### Prompts

1. The `/grill-me` skill, given the feature in the user's own words: "I would
   like you to lead me to develop a discount code feature. This feature allows
   a customer to type a code at the checkout, with that discount code the order
   total would subsequently drop. Here are some requirements of this feature:
   codes must expire when the promotion ends, customers who type expired codes
   should see a message saying that the code is expired without breaking the
   page or the underlying code. Codes must be able to be created and retired.
   If a code is retired that code must not change any order that has already
   used it. The code written should be free from errors redirects to blank
   pages or the customers wrongfully contacting legal. The extent of the
   discount codes must apply to both wide orders(multiple items) or singular
   items. An example of this would be making a discount code for 50% off
   Seraphine for a given date."
2. "Implement this feature"
3. "Ok now that the changes have been made how cn I manually review and test
   the changes to make sure there are no bugs or issus with the code"
4. "can you explain this deviation that I made in more depth", quoting the
   **Where the user overrode the recommendation** bullet from the interim log
   entry (the IDE selection of PROMPTS.md lines 114–121).
5. The session-log prompt from the top of this file.

### Summary

- **Outcome:** Sixteen questions, one at a time, each naming the part of the
  design it settled and recommending an option; then the build. Everything the
  codebase could answer was read rather than asked — the dormant `coupon_code`
  seam, `OrderItem`'s denormalisation precedent, `Product.is_available` as the
  retire pattern, the six call sites of `cart.total()`, and the existing
  `UpdateOrderStatusView` shape.

  `DiscountCode` landed in `orders` with `code`, `kind`, `value`, a nullable
  `product` FK, `starts_at`/`ends_at` and `is_active`; rules on the model
  (`is_live`, `status`, `label`, `discount_for`) and its queryset (`live`,
  `find`). `Cart` gained the FK, and its old `total()` became `subtotal()` so
  that `total()` could mean the amount due — which made `place_order` and all
  three templates discount-aware without editing them. `Order` froze the code's
  name, the dollars taken off, and a `SET_NULL` link. Apply and remove run over
  HTMX on the cart page; `CheckoutView.dispatch` re-checks before card entry
  and `place_order` re-checks inside the transaction. The back office gained a
  fifth tab with list/create/edit and retirement as its own POST action, and
  the dashboard gained `discounts_given()` plus a fourth tile, with Top
  products relabelled "by gross sales". 221 tests passing, ruff clean, five
  demo codes in the seed covering live, scheduled and expired. The
  `coupon_code` parameter was removed and the PRD and plan amended to record
  how the seam actually landed.

  Prompts 3 and 4 changed no code. Prompt 3 produced a manual review script
  with exact expected figures against the seeded world ($616.00 subtotal;
  `THOUGHTS10` → $554.40, `MINDFUL20` → $596.00, `SERAPHINE50` → $367.00) and
  named three things verified in tests but not in a browser: the
  `datetime-local` prefill when editing an existing code, the apply form after
  an HTMX swap, and that `TIME_ZONE = "UTC"` makes entered dates read as UTC
  rather than Central. Prompt 4 was an explanation of the two overridden
  recommendations, grounded in the code as it stood after the follow-up
  session had already grown it.

  *Note for future readers:* this entry describes the feature as built in this
  session. `is_live`/`status` and the single `product` FK have since been
  replaced by `unusable_reason` and `applies_to` + `products` — see the
  2026-09-22 part-two entry below.

- **Deviations:** two of the sixteen recommendations were overridden, and both
  changed the design.

  `kind` + `value` instead of percent-only forced a question percent alone
  never raises — what "$20 off Seraphine" means when three are in the cart. It
  was settled as $20, once, capped at the line total, so the worst case stays
  bounded by the number the merchant typed. The asymmetry with percent (which
  does scale with quantity) is deliberate and is asserted directly by
  `test_a_fixed_amount_comes_off_once_however_many_are_bought`.

  Applying on the **cart page** rather than at checkout opened a real
  time-of-check/time-of-use gap: a code can stop being valid between applying
  and paying. Validation became four call sites over one implementation — the
  apply form, the cart's own total, the checkout guard, and `place_order`. The
  user was told the second check was non-negotiable before agreeing.

  Two follow-up questions were asked after the build: how to manually review
  and test the changes, and a request to explain those two deviations in more
  depth.

- **Sideways:** four tests failed on the first full run. Two were arithmetic
  errors of mine (half of 2 × $349.99 is $349.99, not $350.00) and one assumed
  Django escapes literal template text — in all three the implementation was
  right and the test was wrong. The fourth was a real defect: the back office's
  success message printed the code as typed rather than as stored, and behind
  it sat a worse problem — `ModelForm` checked uniqueness against the
  un-normalised string, so `spring50` would have passed validation beside an
  existing `SPRING50` and then failed at the database. Normalising in
  `clean_code` fixed both, with a regression test for the duplicate case.

  Ruff caught two further things: an import-order violation (auto-fixed) and
  DJ012, the Django style guide's method ordering, which wanted `save` above
  the `normalize` staticmethod.

  Found while reading rather than while building: `CheckoutView.form_valid`
  called `place_order` with no `try`/`except`, so its `ValueError` would have
  rendered a Django 500 — the blank page the brief asked to design against,
  already latent in the code before this feature existed. Fixed here.

  Two process notes. Manually exercising the flow through `manage.py shell`
  hit `DisallowedHost: testserver`, since `ALLOWED_HOSTS` is only relaxed under
  pytest; worked around at runtime, not a defect. And the interim log entry
  written mid-session was appended at the bottom of this file in a freeform
  shape, following CLAUDE.md's "append entries" without reading this file's own
  header, which asks for newest-first and a fixed shape. It has been folded
  into this entry rather than left as a malformed duplicate; no fact it
  recorded was dropped.

## 2026-09-15 — `Product.is_featured` and the Featured badge

### Prompts

1. "Can you add an is_featured field stored as a boolean object, do not
   include the tag/badge on the product such as the accessories defense or
   home assistants tags as that will come later. Simply add it as another
   option like Is available. Also make sure that is_featured is defaulted to
   not featured or false."
2. "Ok now that I do have the is_featured field and I have verified that it
   works well and does not break anything, I would like to implement the
   badge that I talked about earlier. It is important that the badge appears
   in all relevant views this includes the catalog list and the product
   detail page, (make sure it shows up in all relevant locations). Also add
   any tests that you may see fit regarding these two implementations and
   make sure they are working properly."
3. The session-log prompt from the top of this file.

### Summary

- **Outcome:** Two deliberately separated phases, both kept.

  Phase one added `Product.is_featured = BooleanField(default=False)` in
  `products/models.py`, migration `0003_product_is_featured`, the field in
  `ProductForm.Meta.fields` (it renders as another DaisyUI toggle beside
  "Is available" — the back-office form template loops over the form, so no
  template change was needed), and `is_featured` in the admin's
  `list_display` and `list_filter`. 164 tests green.

  Phase two added the badge as one shared partial,
  `templates/products/partials/_featured_badge.html` — a solid
  `badge badge-primary` reading "Featured", rendered only when
  `product.is_featured`. It is included in three places: the catalog card's
  badge row (`catalog.html`, which also covers the category pages, since
  `CategoryView` subclasses `CatalogView` and reuses the template), the
  detail page's status row (`detail.html`, whose wrapper became a
  `flex flex-wrap gap-2` so two badges sit side by side), and the
  back-office product table next to the product name
  (`manage_products.html`). Ten new tests and a `featured_product` fixture
  in `conftest.py`; 174 passing, ruff clean.

- **Deviations:** No recommendation was overridden and no blocking question
  was asked. The split itself was the user's call: prompt 1 explicitly
  deferred the badge ("that will come later"), and prompt 2 opened by
  confirming the field had been verified in the running app before the badge
  work started. One judgment call was made and flagged rather than asked
  about — the badge was deliberately left off the order-side templates
  (cart, checkout, order history, order detail, staff order detail), on the
  grounds that those show what someone bought and "featured" is a browsing
  signal; the user was told and invited to override.

- **Sideways:** Nothing broke; no wrong turns, no failing intermediate
  states. Worth recording as method rather than mishap: four of the ten new
  tests only assert that a string appears on a page, which would pass
  vacuously if the include were wired up wrong. They were checked by
  blanking the partial and confirming those four fail
  (`test_manage_list_badges_featured_products`,
  `test_catalog_badges_only_featured_products`,
  `test_detail_shows_featured_badge`,
  `test_category_page_shows_featured_badge`), then restoring it and
  re-running the full suite. The two catalog/back-office badge tests count
  `">Featured<"` occurrences rather than testing mere presence, so they
  catch both a missing badge and one leaking onto every card.

## 2026-09-22 — Discount codes, part two: limits, scope, organisation, reinstatement

### Prompts

1. The `/grill-me` skill, given four changes in the user's own words:
   usage limits (once per account by default, or a set number, or
   unlimited); an active/inactive split on the discounts page with only
   active codes shown by default; box-selection of several products per
   code instead of one-or-all; and reinstatement of codes, with duplicate
   entry prompting the creator rather than erroring.
2. "Implement the changes."

### Summary

- **Outcome:** Sixteen questions, then the build. `DiscountCode` gained
  `applies_to` + `products` (M2M, replacing the `product` FK),
  `per_user_limit` (default 1), `total_limit` (default unlimited) and
  `counting_since`. Migration `0004` adds the columns, copies the old FK
  into the new set, and only then drops it — `SERAPHINE50` survived
  intact. Uses are counted live from `Order.discount_code_used` via
  `counted_orders`, with `with_usage()` as its SQL twin for the list
  page. `unusable_reason(user)` is the single eligibility answer, called
  from the cart box, `Cart.discount_amount`, `CheckoutView.dispatch` and
  `place_order`. The back office gained `?show=active|inactive|all`, a
  used/limit column, a scrollable product checkbox list, and a
  reinstatement screen that adapts to the existing code's status. 275
  tests pass (54 new), ruff clean.

- **Where the grilling changed the design:** two places, both found by
  reading rather than asking. First, "active" cannot mean `is_active` —
  an expired code still has that flag set, so the obvious reading would
  have left every dead promotion in the default view, which was the exact
  complaint. Active became live-or-scheduled. Second, and more seriously,
  question 7 settled on "an empty product set means the whole order", and
  question 9 had to reopen it: the existing `on_delete=CASCADE` carried a
  comment explaining that *"a code for a deleted product must not quietly
  become a code for everything"*, an M2M has no `on_delete`, and staff can
  delete products from the back office. The implicit spelling would have
  turned 50%-off-Seraphine into 50% off the store. `applies_to` exists
  because of that comment.

- **Already built, contrary to the request:** reinstatement. The brief
  asked to add it, but `ToggleDiscountActiveView` and a "Reactivate"
  button were already there. The real gap was the duplicate path, which
  dead-ended in Django's stock "already exists". That became the work.

- **Deviations:** one recommendation overridden, deliberately. Cancelled
  orders now *release* their use, against my advice — the user was told it
  allows order-and-cancel farming of a one-per-account code and chose it
  anyway. The exclusion sits in `counted_orders` alone, so reversing it is
  one line. Also noted and accepted: "reinstate as-is" cannot revive an
  expired code (flipping `is_active` can't outrun a past date), so that
  button is withheld for expired codes rather than offered as a no-op.

- **Sideways:** five tests failed on the first full run, all of them
  pinned to the old shape — three constructing codes with `product=`, one
  expecting the generic "no longer valid" where the guard now reports the
  code's own reason, and one expecting the duplicate dead-end that was the
  point of the change. All five were updated rather than worked around.
  One template block was written badly first (the typed-terms summary
  computed a label in markup, including a nonsense `yesno` filter) and was
  replaced by a `typed_label` helper on the view, because `target_label`
  reads the products relation and an unsaved instance has no primary key
  to read it with.

## 2026-09-22 — Saved shipping and billing addresses

### Prompts

1. The `/grill-me` skill, given one sentence: "Customers should be able
   to save shipping and billing addresses to their account and reuse
   them at checkout."
2. "Implement the feature."

### Summary

- **Outcome:** Seventeen questions, then the build. `accounts.Address`
  holds role-free rows — a role is something an *order* has, assigned at
  checkout — with an optional `label`, two default flags, and a
  conditional `UniqueConstraint` per role. `make_default` is the only
  thing that moves a default; `AddressQuerySet.remember` is the
  write-back. Checkout pre-fills from the defaults and swaps a chosen
  address into its existing fields over HTMX via
  `CheckoutAddressFieldsView`. `US_STATES` and `zip_validator` moved from
  `orders/forms.py` into `accounts`, since the app that owns addresses
  should own the address vocabulary. 315 tests pass (43 new), ruff clean,
  seed idempotent.

- **What the interview bought:** the feature adds nothing to the order
  pipeline. `Order`, `OrderItem`, `place_order` and `ADDRESS_FIELDS` are
  untouched, and `CheckoutForm` keeps its twelve required fields and its
  zero `clean()` methods. Three options were rejected specifically to
  preserve that: replacing the checkout fields with `ModelChoiceField`s,
  giving `Order` an address FK, and adding "billing same as shipping"
  (which would have needed conditionally-required fields). The form
  docstring calling itself "the codebase's showcase of declarative
  validation" did more design work than any answer I gave.

- **Where reading the code beat asking:** the discount feature's
  `discount_code_used` FK looked like the obvious precedent for linking
  orders to addresses. It isn't — that FK is load-bearing for usage
  limits, `dashboard/queries.py` has no address query at all, and codes
  are never deleted while addresses will be. A mostly-null FK with no
  reader would have invited queries that quietly under-count. Choosing
  `accounts` for the model also surfaced two import problems that only a
  grep found: `zip_validator` living in `orders`, and `StyledModelForm`
  living in `products`, which already imports `accounts.mixins` —
  inheriting it would have made two apps import each other. `AddressForm`
  styles its own widgets instead.

- **A gap the plan had:** the defaults invariant ("a customer with
  addresses always has a default") was settled for creation and deletion
  but not for *unticking* a checkbox, which would have left a customer
  with two addresses and nothing pre-selected. The box is rendered
  disabled on the address that holds the role, so `make_default` needs no
  clearing branch and the invariant holds by construction rather than by
  repair.

- **Scope held three times:** a navbar user-menu dropdown, a project-wide
  address partial, and "billing same as shipping" were all declined as
  separate commits with their own justifications. The dual-default design
  already pre-fills both sections identically for the one-address
  customer, which is who "same as shipping" would have served.
