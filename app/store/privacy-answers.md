# App Privacy answers (App Store Connect → App Privacy)

These match what the app actually does (see `privacy.html`, `wn.js`, `stats/worker.js` and the OneSignal SDK).
If you add a service later (a crash reporter, an ad network, an account), revisit this page first.

**Privacy Policy URL:** `https://word-nyc.com/privacy.html`

## "Do you or your third-party partners collect data from this app?" → **Yes**

### Data types to tick

| Category → type | Collected by | Linked to the user? | Used for tracking? | Purposes |
|---|---|---|---|---|
| Identifiers → **Device ID** | OneSignal (push subscription ID and APNs token, only after the person turns on notifications) | **Yes** (it identifies the device) | **No** | App Functionality |
| Usage Data → **Product Interaction** | OneSignal (sessions, notification opens, favorite-venue tags `fav_<venue>`), the Word NYC stats worker (daily totals of opens, ticket taps, sponsored views and taps, follows) and Cloudflare Web Analytics (page views) | **Yes** for OneSignal's part (it sits on the device's push subscription). The stats worker and Cloudflare parts are anonymous, but Apple asks per data type, so answer Yes. | **No** | App Functionality, Analytics |
| Location → **Coarse Location** | OneSignal (country and time zone, derived from the IP address) | **Yes** | **No** | App Functionality |

Leave everything else unticked: no contact info, no precise location, no contacts, no user content, no
browsing history, no search history, no purchases, no financial info, no health data, no diagnostics, no
sensitive info, no other data.

### Tracking → **No**

Word NYC doesn't link data with other companies' data for advertising, doesn't share it with data brokers,
uses no advertising identifier, and shows no ads in the app. So there's no App Tracking Transparency prompt.
If you ever add ads or an ad-attribution SDK to the app, this answer and the ATT prompt have to change.

## Why these answers

- **No account and no IDs of our own.** wn.js sends `{ metric, app|web, venue slug }` and a "first open
  today" flag. The worker keeps only daily totals; it never stores IP addresses. That part alone would be
  "not linked to you".
- **OneSignal** is the only partner that keys data to the device. Its SDK records device model, OS, language,
  time zone, country (from IP), session counts and notification opens, plus the favorite-venue tags we set.
  We don't send an external user ID, email or phone number to OneSignal, and the location module isn't
  included, so no GPS.
- **Ticket links** open the seller's site in Safari's in-app view (SFSafariViewController). What the seller or
  Impact collects there is theirs, not the app's, and the app can't read it.
- **Map tiles, fonts and the map library** load from OpenFreeMap, Google Fonts and unpkg like any web page.
  Those requests carry an IP address but no data from the app; Apple doesn't require them on the label.

## Privacy manifest

The app's code that touches a "required reason" API (UserDefaults, for the favorites backup) ships its own
`PrivacyInfo.xcprivacy` (`app/native/ios/Sources/WordnycNative/`). Capacitor and OneSignal include theirs.
