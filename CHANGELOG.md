# Changelog

All notable changes to **OpenPost** are documented in this file.

## [0.1.1] - 2026-10-25

### Fixed
- **Architecture Diagram:** Resolved Mermaid rendering syntax errors and updated component flow in `README.md`.
- **Script Sandbox (`pm.*`):** Fixed Chai property assertions (`to.be.true`, `to.be.false`, `to.be.null`, `to.be.undefined`, `to.be.ok`) and mapped HTTP reason phrases to `pm.response.status`.
- **Variable Scopes & Persistence:** Fixed `pm.environment.unset()` and `pm.collectionVariables` persistence, and prevented disabled variables from being injected during execution.
- **Request Engine:** Preserved inline URL query parameters and `#fragment`s when merging explicit `query_params`, and parsed stringified GraphQL `variables` into JSON objects.
- **Authentication Inheritance:** Fixed folder-level and collection-level auth inheritance when requests have `noauth` defaults.
- **SQLite Storage:** Enabled WAL mode and deterministic connection closing across all local database operations.
- **WebUI State & Error Handling:** Preserved non-raw request bodies (`urlencoded`, `formdata`, `graphql`), populated saved auth settings on selection, and added error handling across async UI actions.

### Security
- **V8 VM Sandbox Isolation:** Isolated script execution inside a code-generation-disabled V8 VM context with zero host object references.
- **Local API Hardening:** Restricted CORS to local origins, added `TrustedHostMiddleware` against DNS rebinding, and enforced workspace path and `.json` extension checks on file imports/exports.
- **Transport & Desktop Security:** Enabled TLS certificate verification by default, validated `http`/`https` URL schemes, escaped untrusted strings in the WebUI DOM, and configured a strict Content Security Policy in Tauri.

## [0.1.0] - 2026-10-25

- Initial clean-room release of OpenPost with 22 Model Context Protocol (MCP) tools, native plain-text collection schema (`https://openpost.dev/schema/v1/collection.json`), Postman Collection v2.1.0 round-trip interoperability, FastAPI WebUI, and Tauri v2 desktop builds.
