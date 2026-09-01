import { useEffect, useRef, useState } from "react";
import { Dispute, inr } from "../api";

/* Merchant-facing recovery card.
 *
 * WHAT THE MERCHANT SEES: the money that comes back if this dispute is won,
 * and nothing else. Recovery is amount x net_recovery_fraction. It is NOT
 * probability-weighted, because recovery is binary -- win and the network
 * returns that amount, lose and it returns nothing. There is no outcome in
 * which a merchant receives p x amount x fraction, so showing that figure
 * under the word "recovery" would name money that never changes hands.
 *
 * WHY THERE IS NO SLIDER. An earlier version let the merchant drag p(win) to
 * see the verdict move. It was removed, for two reasons worth recording so it
 * does not come back:
 *
 *   1. Once recovery was correctly decoupled from probability, the slider had
 *      nothing left to drive except a verdict that flips at a single point --
 *      and that point is printed below in words. Dragging to find a threshold
 *      is a slower way to read a sentence already on screen.
 *
 *   2. It was dead on a third of the queue. Measured across the 800 holdout
 *      disputes, the break-even probability sits under 5% on 7% of cases and
 *      over 80% on 25% -- so for roughly one dispute in three the control read
 *      the same verdict across its entire travel. A control that looks
 *      interactive and does nothing is worse than no control.
 *
 * The threshold sentence survives because it answers the real question -- how
 * sure would I have to be for this to be worth doing -- without pretending the
 * merchant has an input into a number the model computes.
 */

type Props = { d: Dispute };

/* The API gives gross = p x amount x NRF at the model's own p. Recovering the
 * fraction by division rather than hard-coding 0.85 keeps this in step with
 * distributions_ref.py: if the constant is swept or changed, this follows. */
function recoveryFraction(d: Dispute): number {
  const denom = d.p_win * d.amount;
  if (denom <= 0) return 0.85;
  return d.ev.gross / denom;
}

function useTween(target: number, ms = 260) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  const t0 = useRef(0);
  const raf = useRef(0);

  useEffect(() => {
    from.current = v;
    t0.current = performance.now();
    cancelAnimationFrame(raf.current);
    const step = (now: number) => {
      const k = Math.min(1, (now - t0.current) / ms);
      const e = 1 - Math.pow(1 - k, 3);   // ease-out cubic
      setV(from.current + (target - from.current) * e);
      if (k < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, ms]);

  return v;
}

export default function RecoveryExplorer({ d }: Props) {
  const nrf = recoveryFraction(d);
  const ifWon = d.amount * nrf;
  const networkCut = d.amount - ifWon;

  /* The cost model stays here and is never rendered. A blocked packet is
   * priced on the escalation branch, which is why resolve_rate is on the
   * payload: a packet a person has to finish only pays out on the share a
   * person can resolve. */
  const rr = d.ev.resolve_rate ?? 1;
  const breakEven = ifWon * rr > 0 ? d.ev.cost / (ifWon * rr) : Infinity;

  /* Phrased as odds rather than a percentage. "Worth it above 0.7%" is a
   * number a merchant has to translate; "more than 1 in 140" is one they can
   * judge against their own experience. */
  const threshold = () => {
    if (!isFinite(breakEven) || breakEven >= 1) {
      return "The cost of contesting this one is more than it can return.";
    }
    if (breakEven < 0.01) {
      return `Worth contesting if you would win more than 1 in ${Math.round(1 / breakEven)} cases like this.`;
    }
    return `Worth contesting if you would win more than ${Math.round(breakEven * 100)}% of cases like this.`;
  };

  const shown = useTween(ifWon);

  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="eyebrow" style={{ marginBottom: 4 }}>Estimated recovery</div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div style={{
          fontSize: 34, fontWeight: 650, letterSpacing: "-0.02em",
          fontVariantNumeric: "tabular-nums", lineHeight: 1.1,
        }}>
          {inr(Math.round(shown))}
        </div>
        <div className="tiny faint">if this dispute is won</div>
      </div>

      <div className="tiny faint" style={{ marginTop: 6 }}>
        {inr(Math.round(d.amount))} disputed, less {inr(Math.round(networkCut))} the
        network keeps to process it.
      </div>

      <div className="tiny faint" style={{ marginTop: 10 }}>
        {threshold()}
      </div>
    </div>
  );
}