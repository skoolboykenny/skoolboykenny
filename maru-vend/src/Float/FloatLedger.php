<?php
declare(strict_types=1);

namespace MaruVend\Float;

use PDO;

/**
 * Float held with BPC. Every movement locks the single float_position row, updates it, and
 * appends a ledger entry, all inside the caller's transaction. CHECK constraints make a negative
 * balance impossible at the database level; UNIQUE(sale_id, entry_type) makes double reservation,
 * double settlement or double release impossible.
 *
 * Invariant: sum(deposits) - sum(settled) - sum(refunds out) = available + reserved.
 */
final class FloatLedger
{
    public function __construct(private PDO $pdo) {}

    public function position(bool $lock = false): array
    {
        $row = $this->pdo->query('SELECT available, reserved, last_deposit_thebe FROM float_position WHERE id = 1' . ($lock ? ' FOR UPDATE' : ''))->fetch();
        if (!$row) {
            $this->pdo->exec('INSERT IGNORE INTO float_position (id, available, reserved, last_deposit_thebe) VALUES (1, 0, 0, 0)');
            return $this->position($lock);
        }
        return array_map('intval', $row);
    }

    public function deposit(int $amount, string $bankRef, string $confirmedBy): int
    {
        $this->requireTx();
        $p = $this->position(true);
        $this->pdo->prepare('INSERT INTO bpc_deposits (amount_thebe, bank_ref, deposited_at, confirmed_by) VALUES (?, ?, NOW(6), ?)')
            ->execute([$amount, $bankRef, $confirmedBy]);
        $depositId = (int) $this->pdo->lastInsertId();
        $this->move(null, $depositId, 'deposit', $amount, $p['available'] + $amount, $p['reserved']);
        $this->pdo->prepare('UPDATE float_position SET last_deposit_thebe = ? WHERE id = 1')->execute([$amount]);
        return $depositId;
    }

    /** Hold the sale amount. Throws InsufficientFloat if it would take the float below zero. */
    public function reserve(int $saleId, int $amount): void
    {
        $this->requireTx();
        $p = $this->position(true);
        if ($p['available'] < $amount) {
            throw new InsufficientFloat('Float exhausted: vending paused until BPC deposit is made.');
        }
        $this->move($saleId, null, 'reserve', -$amount, $p['available'] - $amount, $p['reserved'] + $amount);
    }

    /** Token issued: the reserved amount is consumed. */
    public function settle(int $saleId, int $amount): void
    {
        $this->requireTx();
        $this->requireEntry($saleId, 'reserve');
        $this->forbidEntry($saleId, 'release');
        $p = $this->position(true);
        $this->move($saleId, null, 'settle', $amount, $p['available'], $p['reserved'] - $amount);
    }

    /** BPC confirmed no token: return the reserved amount to available. */
    public function release(int $saleId, int $amount): void
    {
        $this->requireTx();
        $this->requireEntry($saleId, 'reserve');
        $this->forbidEntry($saleId, 'settle');
        $p = $this->position(true);
        $this->move($saleId, null, 'release', $amount, $p['available'] + $amount, $p['reserved'] - $amount);
    }

    /** Service fee accrued on a successful sale (recorded for invoicing; does not move the float). */
    public function fee(int $saleId, int $fee): void
    {
        $this->requireTx();
        $p = $this->position(true);
        $this->move($saleId, null, 'fee', $fee, $p['available'], $p['reserved']);
    }

    public function belowAlert(int $alertPct): bool
    {
        $p = $this->position();
        return $p['last_deposit_thebe'] > 0 && $p['available'] * 100 < $p['last_deposit_thebe'] * $alertPct;
    }

    private function move(?int $saleId, ?int $depositId, string $type, int $amount, int $available, int $reserved): void
    {
        $this->pdo->prepare('UPDATE float_position SET available = ?, reserved = ? WHERE id = 1')->execute([$available, $reserved]);
        $this->pdo->prepare('INSERT INTO float_ledger (sale_id, deposit_id, entry_type, amount_thebe, available_after, reserved_after) VALUES (?,?,?,?,?,?)')
            ->execute([$saleId, $depositId, $type, $amount, $available, $reserved]);
    }

    private function requireEntry(int $saleId, string $type): void
    {
        $st = $this->pdo->prepare('SELECT 1 FROM float_ledger WHERE sale_id = ? AND entry_type = ?');
        $st->execute([$saleId, $type]);
        if (!$st->fetchColumn()) {
            throw new \LogicException("Sale $saleId has no $type entry");
        }
    }

    private function forbidEntry(int $saleId, string $type): void
    {
        $st = $this->pdo->prepare('SELECT 1 FROM float_ledger WHERE sale_id = ? AND entry_type = ?');
        $st->execute([$saleId, $type]);
        if ($st->fetchColumn()) {
            throw new \LogicException("Sale $saleId already has a $type entry");
        }
    }

    private function requireTx(): void
    {
        if (!$this->pdo->inTransaction()) {
            throw new \LogicException('Float movements must run inside a transaction');
        }
    }
}
