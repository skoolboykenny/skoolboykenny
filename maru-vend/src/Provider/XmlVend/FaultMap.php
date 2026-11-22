<?php
declare(strict_types=1);

namespace MaruVend\Provider\XmlVend;

use MaruVend\Provider\ProviderResult;

/**
 * XMLVend 2.1 fault types (NRS 009-6-10 4.6.3, figures 47-48) mapped to one action each
 * (clause 7.9, tender Annex E).
 *
 *  BusinessRuleEx and its subtypes   the server refused the request by rule: no token issued
 *  SystemEx                          server-side failure while answering: no token issued, retry later
 *  LastResponseEx (on advice)        the request was not processed: safe to treat as failed/repeat
 *  ClientIDSSLEx                     our certificate / client ID rejected: nothing processed, alert ops
 *  XMLVendSchemaEx, UseCaseSupportEx our request was not understood: on a credit vend we still
 *                                    recover via advice rather than assume, otherwise fail and alert
 *  Unknown / new subtypes            treated as BusinessRuleEx if their name says so, otherwise uncertain
 *
 * Utility-specific extensions (e.g. BPC's own BusinessRuleEx subclasses) are recognised by name
 * suffix, so they are handled correctly without code changes; their customer messages are shown.
 */
final class FaultMap
{
    /** Known BusinessRuleEx subtypes (figure 48). Extensions ending in "Ex" not listed here are classified below. */
    public const BUSINESS_RULE = [
        'BusinessRuleEx', 'BlockedMeterEx', 'ClientIDAuthorisationEx', 'FBEEx', 'ConfirmCustomerEx', 'LatestKRNEx',
        'CancelEx', 'CheckBatchTotalEx', 'MSNOCheckDigitEx', 'DebtEx', 'RequestAuthorisationEx', 'EndBatchEx',
        'SGCAuthorisationEx', 'InsufficientMeterDataEx', 'STSDataEx', 'ReprintDepositSlipEx', 'VendorCreditEx',
        'ReprintEndBatchEx', 'ServiceChrgEx', 'ReprintEx', 'UnknownMeterEx', 'RequireMeterCardEx',
        'UnknownMeterUpdateMtrKeyEx', 'StartBatchEx', 'UpdateMtrKeySameEx', 'VerifyTokenEx',
    ];

    public static function outcome(string $type, string $op): string
    {
        $type = self::localName($type);
        return match (true) {
            in_array($type, self::BUSINESS_RULE, true) => ProviderResult::BUSINESS_FAULT,
            $type === 'SystemEx' => ProviderResult::SYSTEM_FAULT,
            $type === 'LastResponseEx' => ProviderResult::NOT_FOUND,
            $type === 'ClientIDSSLEx' => ProviderResult::SYSTEM_FAULT,
            in_array($type, ['XMLVendSchemaEx', 'UseCaseSupportEx', 'XMLVendFaultEx', 'ConfirmationEx', 'ReversalEx'], true)
                => $op === 'creditvend' ? ProviderResult::UNKNOWN : ProviderResult::BUSINESS_FAULT,
            // Utility extensions: "...SystemEx" are system faults; other "...Ex" are business rules.
            str_ends_with($type, 'SystemEx') => ProviderResult::SYSTEM_FAULT,
            str_ends_with($type, 'Ex') && $op !== 'advice' => ProviderResult::BUSINESS_FAULT,
            default => $op === 'creditvend' || $op === 'advice' ? ProviderResult::UNKNOWN : ProviderResult::SYSTEM_FAULT,
        };
    }

    public static function localName(string $qname): string
    {
        $p = strrpos($qname, ':');
        return $p === false ? $qname : substr($qname, $p + 1);
    }
}
