# Word NYC for iPhone

The app is a native shell (Capacitor 8) around https://word-nyc.com, so site changes show up in the app
without an App Store update. It adds what a web page can't do well on iPhone: native push for the noon picks
(OneSignal's iOS SDK, same OneSignal app as the website), Follow-a-venue alerts, an in-app Safari view for
ticket links, the iOS share sheet, an offline copy of tonight's lineup, and no ads.

It's built and uploaded to TestFlight by GitHub Actions on a macOS runner (`.github/workflows/ios.yml`).
You never need Xcode. (You can still open `app/ios/App/App.xcodeproj` on your Mac after `npm install && npx cap sync ios` in `app/`.)

## Setup, in order

**1. Nothing yet.** Each push that changes `app/` builds the app for the iOS Simulator as a compile check.
The App Store screenshots are already in `app/store/screenshots/`.

**2. App Store Connect API key.** App Store Connect → Users and Access → Integrations → App Store Connect API →
Team Keys → +. Name it `GitHub`, access **App Manager**, Generate. Download the `.p8` file (only possible once)
and note the **Key ID** and the **Issuer ID** shown above the list.

**3. GitHub secrets.** Repo → Settings → Secrets and variables → Actions → New repository secret:
- `ASC_KEY_ID`: the Key ID
- `ASC_ISSUER_ID`: the Issuer ID
- `ASC_KEY_P8`: the whole text of the `.p8` file, including the `-----BEGIN PRIVATE KEY-----` and `-----END…` lines

**4. First run.** Actions → **iOS app** → Run workflow (leave "upload" ticked). It registers the bundle ID
`com.wordnyc.app` with Push Notifications, then stops with "there's no app record yet". That's expected.

**5. Create the app record.** App Store Connect → Apps → + → New App: platform iOS, name
`Word NYC: Live Music Tonight`, primary language English (U.S.), bundle ID `com.wordnyc.app`, SKU `word-nyc-ios`.

**6. Second run.** Run the workflow again. About 15 minutes later the build is in App Store Connect →
TestFlight (Apple then processes it for 5–30 minutes). Add yourself under TestFlight → Internal Testing and
install it with the TestFlight app.

**7. Push for the app (OneSignal + Apple).** developer.apple.com → Certificates, IDs & Profiles → Keys → + →
name `OneSignal`, tick **Apple Push Notifications service (APNs)**, Continue, Register, Download the `.p8`
(again, only once) and note its Key ID. Your **Team ID** is at developer.apple.com → Account → Membership details.
Then OneSignal → the Word NYC app → Settings → Push & In-App → **Apple iOS (APNs)** → choose ".p8 Auth Key",
upload the file and enter the Key ID, Team ID and bundle ID `com.wordnyc.app`. From then on the noon push
reaches the app too (it's the same send as the website's).

**8. Stats for sponsors (Cloudflare, free).**
- Cloudflare → My Profile → API Tokens → Create Token → template **Edit Cloudflare Workers** → add the
  permission Account → **D1** → Edit → Create. Copy the token.
- Your **Account ID** is on the right side of Workers & Pages. If you've never used Workers, open Workers &
  Pages once and pick a workers.dev subdomain.
- Add secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `STATS_KEY` (any long random string, e.g. run
  `openssl rand -hex 24 | pbcopy` on your Mac and paste).
- Actions → **Deploy stats worker** → Run workflow. It switches counting on for the site and the app.
- Your report: `https://word-nyc.com/app-stats.html#key=<STATS_KEY>` (bookmark it; not linked or indexed).

**9. Submit.** Fill in the version page from `store/listing.md`, the App Privacy section from
`store/privacy-answers.md`, App Review notes from `store/review-notes.md`, upload `store/screenshots/*.png`,
pick the build, and press Submit for Review.

## Day to day

- **New build:** bump `version` in `app/package.json` for a new App Store version (build numbers count up by
  themselves), then Actions → iOS app → Run workflow. Site-only changes don't need a new build.
- **Fresh screenshots:** Actions → **App Store screenshots (Linux)** → Run workflow (about 3 minutes).
- **Sell the noon push:** in `sponsored.json`, add `"push": true` to the placement (see the main README.md and the
  "Featured in the noon push" tier on `advertise.html`; set its price there). Only one per day leads the push.
- **Sponsor numbers:** the stats page above. "Copy" on a venue's row gives a one-line summary to email.

## How it fits together

| Piece | Where |
|---|---|
| Capacitor config (loads word-nyc.com, adds `WordNYCApp/1.0` to the user agent) | `capacitor.config.json` |
| Native code: push, tags, in-app browser, ad filter, share, offline | `native/ios/Sources/WordnycNative/` |
| Xcode project (Capacitor's SPM template + push entitlement, icon, portrait iPhone) | `ios/` |
| Page shown with no connection (lists the saved lineup) | `www/offline.html` |
| Signing with the API key: bundle ID, certificate, profile | `ci/asc.py` (+ Codemagic's open-source CLI tools) |
| Screenshots (Linux Chromium; simulator version in `ci/screenshots.py`) | `ci/web-screenshots.js` |
| Site side: app detection, favorites, counts | `../wn.js`, `../index.html` |
| Noon push: sponsored lead, favorites variants | `../scraper/notify.py` |
| Stats worker and report | `../stats/`, `../app-stats.html` |

The distribution certificate's private key is stored encrypted in `ci/dist-cert-key.enc` (created by the first
release build; only decryptable with your `ASC_KEY_P8`), so builds reuse one certificate.

## Limits to know

- **OneSignal free plan:** mobile push is free up to 1,000 monthly active app users, and each person can carry 6
  tags (favorites use up to 5; more follows are kept on the phone but only the 5 newest are in the noon push).
  Past 1,000 app users, either upgrade OneSignal or switch the app's push to Apple's service directly (free,
  sent from the same noon workflow).
- **Unique users** are counted per day (a flag on the device), never across days, because nothing identifies a
  person. The report shows daily average and peak.
