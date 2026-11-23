# XMLVend regional profile: what we take from Eskom's published material

BPC runs a CONLOG vending server; Eskom does not. But Eskom publishes the only complete public
reference for running XMLVend 2.1 (NRS 009-6-10) in production: its extensions, its client
guideline, its vendor function table and its certification test suite. We use that material as the
**regional reference profile** for our sample system, and keep only what serves the BPC tender.

**What we claim:** XMLVend 2.1 (NRS 009-6-10) base, with the regional reliability rules applied and
a BPC profile to be confirmed against BPC's schemas. **What we do not claim:** "Eskom compliant",
nor that CONLOG behaves the way Eskom's server does. Every item below marked *assumption* has to be
confirmed with BPC (see `xmlvend.md`, "To confirm with BPC").

The question this profile answers for an evaluator is **"can a token be lost or sold twice?"**
The answer is **no, by construction**. Every paid sale ends with exactly one token or exactly one
refund. That holds after a timeout, a crash or a site failover. Ambiguous sales are held, never
guessed.

## Sources reviewed (eskom.co.za/prepayment)

| Document | Used for |
|---|---|
| NRS 009-6-10 XMLVend 2.1 | Base protocol (already the basis of `src/Provider/XmlVend`) |
| Eskom XMLVend Extensions, Restrictions and Optional Fields 1.8 | Restrictions, extra faults, optional fields |
| Guideline for the Development of Online Vending Clients 1.2 | No reversals; detection of missing vend responses (sign-in check) |
| Functionality Required From Online Vending Services (2010) | Which functions each device type may offer |
| XMLVend Test Suite Business Rules 1.2, Test Suite Setup | Certification checks; SSL setup (CA, client cert, CRL) |
| Receipt Formats, step-tariff receipt format | Receipt fields |

A five-advisor review (2026-11-22) sorted them into keep, adapt and drop. All five advisors agreed
on the lists below. They disagreed only on how far to rebuild the reference test suite (see the end).

## Keep: implemented

| Rule (source) | Where | Why it matters to BPC |
|---|---|---|
| No reversals, no cancel, no confirmation advice. Advice is `LastRespAdviceReq` only (ext. 5.5; test rule 2.1.2; guideline 1.4.7) | `XmlVendProvider` | The server never depends on the client, so there is no reversal fraud window |
| **Sign-in check**: before a terminal sends anything, advise its last credit vend if no definite answer was received (guideline 1.4.7) | `XmlVendProvider::signIn()`; runs before every send and at worker start | A crash or failover mid-vend can no longer overwrite the server's last response for that terminal. This closes the main gap in the earlier client |
| msgID stored before sending, unique per terminal (NRS 5.2.4.3) | `allocateMsgId` | An advice can always name the exact request |
| `DuplicateMsgIDEx` means this request was not processed: retry with a new msgID and alert (ext. 4.5; test rule 2.1.4) | `FaultMap` | The name-suffix rule would have refunded it as a business fault |
| `IndeterminateLastResponseEx` means hold for reconciliation; the terminal may carry on (ext. 4.5) | `FaultMap`, `signIn()` | Never failed, and the terminal is not blocked forever |
| Meter-data faults (`MeterDataMisMatchEx`, `RequireMeterCardEx`, `InsufficientMeterDataEx`) are final, the customer is shown a message, no retry (test rules 2.2) | `FaultMap` | Clear message to the customer, no wasted retries |
| clientID is a 13-digit EANDeviceID (ext. 5.1; test rule 2.1.5); Electricity only; purchase in currency only (ext. 5.8) | `XmlVendConfig` (start-up check), `XmlVendMessages` | Fails at start-up, not at BPC |
| Mutual TLS; certificate CN = clientID, otherwise `ClientIDSSLEx` (test rule 2.1.3) | transport; `ClientIDSSLEx` alerts operations | A certification gate |
| gzip off by default; the certification message interceptor cannot read compressed messages | `XmlVendConfig::gzip` (`MV_XV_GZIP`) | Needed to pass the interceptor; turn on only with BPC's agreement |

## Adapt

- **Device IDs.** Keep the EAN format only if BPC issues EANs (*assumption*). The terminal ID scheme is configurable (`MV_XV_TERMINAL_PREFIX`).
- **Free basic electricity (`fbeDue`), debt, `OverRecCredTokenIssue`.** Parse them if present, never require them. BPC may run a lifeline tariff later.
- **Receipts.** Take the field set from Eskom's receipt formats and apply BPC wording, Pula, the BPC fixed charge, the government levy and VAT for Botswana (already in the receipt parser). Apply it to SMS/USSD and POS slips.
- **Vendor function table.** Rework it as our compliance matrix by channel. USSD, app and web are *customer-driven*: number-only vending, purchase, reprint and automatic advice. Blind vending and key changes are **prohibited** on them. The POS is *operator-driven*. Keep the table in the tender.
- **Test suite.** Use our own simulator, with the same strict last-response-per-terminal behaviour and the regional fault names. Also validate against the published schemas and run fault injection (`lost`, `lostfail`, `lostindet`, `processing`, `down`). If BPC accepts it, also run Eskom's reference client and message interceptor against the simulator as outside evidence.

## Drop (Eskom-only; no tender score, real effort)

- The PSG customer-support terminal functions: credit transfer, engineering tokens, test tokens.
- Customer fault reports routed to GTX.
- Pay-account and debt use cases, unless BPC asks for them.
- Grace purchases and meter-card encoding: these belong to the operator UI and hardware, not to an aggregator.
- The guideline's ruggedness and operator-UI advice, for unattended channels.
- Vendor statements and deposit slips: optional, and not needed by BPC.

## Reliability and performance decisions this material drives

1. **The terminal is the unit of exclusivity.** One terminal has one owner and one request in flight. Throughput scales by adding terminals (ask BPC for a pool of client or terminal IDs), never by running one terminal concurrently. Pool size ≈ peak sales/s × (BPC timeout + advice window), plus 30% headroom.
2. **Terminal IDs are bound to the host and worker** (`ProviderFactory::terminalId`), so the two sites never share a terminal. After a failover, the surviving site resolves the dead site's open sales with advice on the original terminal ID. When the failed site returns, its workers sign in first. Next step: a fenced lease per terminal in the quorum store, to also rule out two processes on one host with the same worker ID.
3. **Float waits for a definite outcome.** Reserve before sending; settle on a token; release only on a definite "not processed". Ambiguous sales stay reserved. Run a daily reconciliation against BPC sales, with an owner and a deadline for each exception.
4. **`SystemEx` retry with a new msgID** is safe only if CONLOG's `SystemEx` always means "not processed" (*assumption*; ask BPC). Otherwise switch it to advise first.
5. **Fast-fail on short sessions.** USSD has a hard session timeout. Show "confirming, do not pay again" and deliver the token by SMS rather than hold the session.
6. **Targets to publish in the tender:** p95 vend time, rate of uncertain outcomes, time to resolve a held sale, and failover recovery time (measured with `bin/mv loadtest` and `scripts/fault-demo.php`).

## Open question from the review

The advisors split on how far to go with the reference test suite. The view that won: our
simulator plus schema validation is the primary evidence. Running Eskom's 2012-era Java/Tomcat
suite is optional supporting evidence, and is worth doing only if BPC's certification pack
(Annexure 4) points to it.
