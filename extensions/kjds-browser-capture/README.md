# KJDS Browser Capture

Load this directory as an unpacked Manifest V3 extension only for local KJDS
acceptance.

The helper has exactly three permissions:

- `activeTab`
- `scripting`
- `storage` (session-only pending envelope)

It has no `host_permissions`, content scripts, cookies, localStorage transfer,
network interception, internal API calls, `<all_urls>` access or CAPTCHA
behavior. A capture requires an explicit click on the current 1688/Ozon
product tab, followed by a separate authenticated save click in
`http://127.0.0.1:3000/capture-inbox`.

The captured price remains a C-grade public observation. It is not a Supplier
Offer, actual cost, Product, Listing, Approval, Permit or external write.
