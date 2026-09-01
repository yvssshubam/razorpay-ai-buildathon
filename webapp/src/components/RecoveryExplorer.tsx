import { useEffect, useRef, useState } from "react";
import { Dispute, inr } from "../api";
type Props = { d: Dispute };
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