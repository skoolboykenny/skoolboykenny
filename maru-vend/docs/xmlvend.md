# XMLVend 2.1 client (clause 7.1)

`src/Provider/XmlVend/` implements the XMLVend 2.1 client for BPC's CONLOG vending server. It is
built from the public specification **NRS 009-6-10:2010** (Eskom) and the published XMLVend base
schema (`tests/fixtures/xmlvend-base-2.0.xsd`, Apache License 2.0).

## Messages

| Use case (NRS 009-6-10) | Request | Used for |
|---|---|---|
| Confirm customer details (4.5.2.3, 4.7.3.3) | `confirmCustomerReq` | Show the customer's name before payment; honours `canVend`, `minVendAmt`, `maxVendAmt` |
| Purchase credit token (4.5.2.10, 4.7.3.16) | `creditVendReq` | Buy the token (final); Electricity, currency amount, cash pay type |
| Issue advice: advise last response (4.5.4.2 c) | `adviceReq` (`LastRespAdviceReq`) | Recover the outcome when a credit vend's response is lost |

- **Transport:** SOAP 1.1 over HTTPS, with `SOAPAction: ""`, optional gzip, mutual TLS, inside the IPsec tunnel.
- **Timeout:** BPC's timeout plus the worker margin (clause 7.8).

## Safety rules

1. **Advise last response only.** It is the spec's lowest-risk mechanism. Reversals are never sent.
2. **A new message ID for every request, stored before sending.** The msgID is a 14-digit
   timestamp plus a unique number (1 to 999999), unique per terminal.
3. **One terminal ID per queue worker.** An uncertain credit vend is resolved with advice on that
   terminal *before* the terminal sends anything else (spec 4.5.4.2, implementation note 1).
4. **`LastResponseEx` means "not processed"** only when the terminal has sent nothing since. Otherwise
   the result is ambiguous, and the sale is held for manual reconciliation. It is never marked failed.
5. **A credit vend is never assumed failed on an unclear fault.** Schema faults, unknown fault types
   and unreadable responses are all recovered with advice first.

## Fault handling (Annex E)

| XMLVend fault (4.6.3, figs 47-48) | Outcome | Action | Customer |
|---|---|---|---|
| Success with a 20-digit STS token | OK | Store token, key change tokens and receipt; settle float; accrue fee | Token, receipt and SMS |
| `BusinessRuleEx` and subtypes (`BlockedMeterEx`, `UnknownMeterEx`, `VendorCreditEx`, `MSNOCheckDigitEx`, `LatestKRNEx`, ...), and BPC's own extensions | Business fault | Abandon; release float; refund payment | BPC's `custMsg`, e.g. "This meter is blocked" |
| `SystemEx` | System fault: not processed | Retry with a **new** msgID after a back-off (max 5), then fail | "Processing" |
| `ClientIDSSLEx` | System fault | Stop and alert operations (certificate or client ID problem) | "Temporarily unavailable" |
| No response / timeout after sending / HTTP error | Uncertain | Advise last response on the same terminal | "Confirming with BPC, do not pay again" |
| `LastResponseEx` (terminal unused since) | Not processed | Fail; release float; refund | "You have not been charged" |
| `LastResponseEx` (terminal used since) | Ambiguous | Hold; reconcile with BPC records; alert after 2 h | Token by SMS when resolved |
| `XMLVendSchemaEx`, `UseCaseSupportEx`, unknown types on a credit vend | Uncertain | Advise last response; alert operations | "Confirming with BPC" |
| Same faults on confirm customer | Business fault | Show the message; nothing was bought | Message |

## Testing

- `vendor/bin/phpunit --filter XmlVend` runs 13 tests:
  - Generated advice requests and fault responses validate against the published base schema.
  - Against the simulator's SOAP endpoint: sale, blocked meter, SystemEx retry, lost response
    recovered, lost without token, the ambiguous terminal, key change tokens, unknown meter, and a
    full sale through the vend service.
- Full stack on XMLVend: `bin/mv setting:set provider xmlvend`, restart the workers, then run
  `bin/mv loadtest` and `scripts/fault-demo.php`.

## To confirm with BPC and its server supplier before certification

The spec says the XSD schemas, not the class diagrams, are definitive (5.2.2.1). The base schema is
public; the **revenue** schema is not available online. Ask BPC for:

1. **Schemas.** The revenue and base XSDs and WSDL for the version BPC runs, plus any BPC extension
   schema (`bpc-xmlvend-revenue-2.1.xsd`). Then check the element names in
   `XmlVendMessages` (`confirmCustomerReq`, `creditVendReq`, `purchaseValue`, `confirmCustResult`,
   `creditVendReceipt`, `transactions/tx`) against them.
2. **Advice.** Which mechanism BPC has configured (this client assumes "advise last response"), and
   whether last response is kept per message or only per terminal.
3. **Charges on the receipt.** How the fixed charge and government levy appear (we read
   `ServiceChrgTx` descriptions), and whether VAT is inside or on top of each transaction amount.
4. **Credentials.** Our client ID (EAN), operator name and password, terminal ID rules, and the client
   certificate and CA.
5. **Behaviour.** The confirm-customer requirement, minimum and maximum amounts, BPC's timeout value,
   and the test endpoint plus the certification test pack (Annexure 4).
