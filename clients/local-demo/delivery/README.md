# KJDS Local Demo delivery evidence

This layer verifies and packages the existing portable demo without importing or
calling any production application. It writes only below `clients/local-demo/.runtime`.

## Run

```powershell
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH='C:\Program Files\Google\Chrome\Application\chrome.exe'
npm run test:delivery
npm run verify:delivery -- --output-dir .runtime/bas196-final
```

The verifier performs two clean rounds. Each round builds and verifies the portable
ZIP, extracts it into a bounded temporary directory, launches it on
`127.0.0.1:43195`, verifies fresh online and persisted-profile offline cold starts
at 1440px and 390px, exercises two isolated in-memory sessions, scans source,
`dist`, and ZIP payloads, and runs cleanup twice.

Chromium persistent profiles use a short directory below the operating-system
temporary root so the same Gate remains valid from deeply nested Windows checkout
paths. Every such directory has a BAS-196 ownership marker; cleanup verifies the
resolved temp boundary and marker before recursive removal, then proves no profile
residual remains. Final delivery artifacts still exist only below `.runtime`.

The delivery ZIP contains only deterministic inputs: the portable ZIP and manifest,
the normalized deterministic evidence record, its embedded manifest, and this
README. Runtime observations such as screenshot hashes and round duration are kept
outside that deterministic hash and are explicitly listed in `delivery-evidence.json`.

No account, credential, customer text, network proxy, production import, or external
write is accepted. The two screenshots and command logs are evidence sidecars, not
runtime dependencies.
