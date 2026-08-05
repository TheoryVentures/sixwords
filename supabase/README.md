# sixwordidea.com backend setup

The published-ideas backend is a single Supabase project. One-time setup:

## 1. Create the project

Create a project at [supabase.com](https://supabase.com), then run
`schema.sql` in the SQL editor. It creates the `ideas` table with row-level
security: public reads, inserts only for signed-in users.

## 2. Configure auth

Under **Authentication → Sign In / Up**, make sure **Email** is enabled with
**OTP** (one-time codes). No other providers are needed — `sixwords login`
uses email codes only.

On the free tier with the built-in email provider, sign-in emails carry a
magic **link** (templates can't be customized), so `sixwords login` asks
you to paste that link. The built-in provider also only delivers to the
project's team-member emails and is rate-limited to a few messages an
hour — fine for personal publishing. To let other people sign in (and to
switch the emails to a pasteable 6-digit code via a `{{ .Token }}`
template), configure a custom SMTP provider under **Authentication →
Emails → SMTP settings**.

Signups are open by default, which means anyone can create an account and
publish. To restrict publishing to people you invite, turn off **Allow new
users to sign up** and invite emails from the Authentication dashboard
instead. Junk publishes can always be deleted from the table editor, and
users can be banned from the auth dashboard.

## 3. Wire the CLI and site build

From **Settings → API**, take the project URL and the `anon` `public` key:

- Bake them into `DEFAULT_SUPABASE_URL` / `DEFAULT_SUPABASE_ANON_KEY` in
  `sixwords/publish.py` (they are public values; safe to commit), and/or
- Set `SIXWORDS_SUPABASE_URL` / `SIXWORDS_SUPABASE_ANON_KEY` in the
  environment.

For the GitHub Pages build, add the same two values as repository **Actions
variables** named `SIXWORDS_SUPABASE_URL` and `SIXWORDS_SUPABASE_ANON_KEY`
(Settings → Secrets and variables → Actions → Variables).

## 4. Rebuild the site on publish

The site workflow (`.github/workflows/site.yml`) rebuilds on push, on a
schedule, and on a `repository_dispatch` event. To make publishes go live
within a minute, add a database webhook that fires that event:

1. Create a GitHub fine-grained personal access token with **Contents:
   read/write** on this repo.
2. In Supabase, go to **Database → Webhooks** and create a webhook on
   `INSERT` into `public.ideas` with:
   - URL: `https://api.github.com/repos/TheoryVentures/sixwords/dispatches`
   - Method: `POST`
   - Headers:
     - `Authorization`: `Bearer <your token>`
     - `Accept`: `application/vnd.github+json`
     - `Content-Type`: `application/json`
   - Body: `{"event_type": "idea-published"}`

Without the webhook everything still works; publishes just wait for the
next scheduled build.

## 5. Point the domain at GitHub Pages

In the repo, enable **Pages** with source **GitHub Actions**, set the custom
domain to `sixwordidea.com`, and add the DNS records at your registrar:
`A` records for the apex pointing at GitHub Pages' IPs (185.199.108.153,
185.199.109.153, 185.199.110.153, 185.199.111.153) and a `CNAME` from `www`
to `theoryventures.github.io`. Enable **Enforce HTTPS** once the certificate
is issued.
