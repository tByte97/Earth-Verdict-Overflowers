# PR #16 review fixes

Review: https://github.com/tByte97/Earth-Verdict-Overflowers/pull/16#pullrequestreview-5905235919

| Point | Resolution | Verification |
|---|---|---|
| 1. Live form/catalogue mismatch | Live spec has no demo variable. Catalogue initialization selects a returned id, and submit checks membership. Empty/invalid catalogues are errors. | Backend-only id matches the POST; empty catalogue disables submit. |
| 2. Incomplete validation / blank page | Full nested Zod schemas validate case, variable, reason, methods, witness, detection, extrapolation, scenarios, provenance and metadata. Root/result error boundaries provide recovery. | Malformed-field matrix and deliberate render-failure harness. |
| 3. Contract/type drift | Types are inferred from schemas. Optional witness rates and nullable provenance versions are accepted. No-station is a null witness only. Case-data cast removed. | Optional-rate/version success test, illegal agreement rejection and canonical snapshots. |
| 4. Derived provenance | Derived fields link to explicit backend-statistics, detection-simulation, extrapolation or scenario method records. Only measured rows link to recognised unambiguous provider URLs. Free-text descriptions never assign a role. | Reordered/renamed provenance still maps measured series; detection and future rows never masquerade as NASA observations. |
| 5. City aliases | Explicit place-id alias table, with no Kyiv fallback for unknown cities. | Warsaw does not match Kyiv aliases. |
| 6. Live announcements | Distinct initial/catalogue-loading, edited, loading, success and error phases. | Initial and error messages do not announce changed parameters. |
| 7. Null descriptions | Omit absent caveats and append a station name only when a witness exists. | No empty caveat paragraph or dangling station wording. |
| 8. Browser/server assumptions | Playwright Test owns a webServer and uses installed Playwright Chromium by default. | Suite runs without an existing Vite server or Edge. |
| 9. Package manager/workspace | Standard pnpm 9/10 onlyBuiltDependencies in package.json; remove frontend workspace config and explicitly scope Vite fs.allow to the repository. | pnpm 10 install, type-check, build and canonical JSON imports in browser tests. |
| 10. Font import | HTML preconnect + stylesheet with display=swap; remove CSS @import. | Production build and browser layout review; system-font fallbacks remain. |

The review-fix commit itself did not restructure the globe layout. A subsequent explicit
user request integrates the globe contributor’s branch in a 60/40 workspace while preserving
the validated form, lifecycle announcements and error boundaries. See README.md for the
current layout behaviour.
