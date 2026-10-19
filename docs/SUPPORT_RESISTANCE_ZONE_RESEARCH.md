# Support/resistance zone research

`scripts/atc_sr_zones.py` implements the single fixed hypothesis
`causal-pivot-zone-memory-v1`. It is a research component only. It is not imported
by the scanner, E manual bridge, TradingView scripts or an order path. It neither
downloads data nor sends notifications. No performance experiment has yet
validated this candidate on a corrected/common-basis feed.

## Why this candidate exists

Research provides evidence for some level effects, not universal settings:

- [Osler (2000), NY Fed](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)
  compares prospectively published institutional FX levels with random levels.
  The ability to interrupt a trend is distinct from a profitable trading rule.
- [Garzarelli et al. (2014), Scientific Reports](https://pmc.ncbi.nlm.nih.gov/articles/PMC3967202/)
  studies repeated bounces in tick data for nine LSE stocks. Its second-scale
  findings do not establish an effect for BIST daily or hourly bars.
- [Chung and Bellotti (2021), author preprint](https://arxiv.org/html/2101.07410v1)
  investigates regions, previous bounces and heterogeneous memory decay in
  EURUSD, LLOY and Brent. Its full-series width calculation is not copied: all
  scales below use past data available at the decision time.
- [Tengelin and Sopasakis (2020)](https://www.aimspress.com/aimspress-data/nar/2020/4/PDF/NAR-02-04-021.pdf)
  studies tick-data clustering; mixed significance and omitted transaction costs
  do not justify assuming a more complex clusterer will improve our OHLC method.

The ATR width, half-life and eligibility counts below are our preregistered
engineering hypotheses. None is presented as a paper-established optimum.

## Fixed causal definition

`build_sr_zones(frame, as_of=aware_timestamp)` accepts a CanonicalFrame-like
object. It requires consistent positive OHLC and ordered, nonoverlapping aware
timestamps, source, symbol, timeframe, snapshot, price-basis and revision
metadata. Marked trailing partial and future bars do not confirm pivots or settle
episodes. Volume is optional and never read or synthesized.

The replay has a 30-closed-bar warm-up. A pivot has three left and three right
closed bars; ties select the rightmost extreme within this confirmation window.
The zone is available at the third right bar's close, never at the old extreme's
timestamp. The pivot's original reversal is not a successful revisit.

A new zone's center is the pivot price. Its half-width is 0.25 ATR14 at
confirmation, raised to a supplied valid tick size if necessary. ATR seeds with
the first 14 true ranges' mean and then uses Wilder smoothing. Geometry never
moves. Later same-kind pivots inside it join the existing zone, choosing the
closest center and then the older zone if needed. Joining cannot expand a zone
through a chain of near neighbors. The zone stops accepting visits 120 bars
after its seed pivot. Broken support is not relabeled resistance.

A visit must approach from the correct side after first moving one ATR clear
of that side's region edge. Only a later bar can then enter the region. One
multi-bar stay is one episode. Entry barriers freeze the ATR known **before**
the entry bar: a bounce is one ATR beyond the approach-side edge; penetration
is half an ATR beyond the opposite edge. The horizon is ten bars, including
entry. Resistance mirrors support.

At most one episode per symbol/side may occupy an OHLC bar. When several zones
could be entered, the approach edge closest to the previous close is considered
first, then the older zone. A pending episode reserves that entire side for the
bar even if it resolves within the bar; another intrabar entry sequence cannot
be inferred from OHLC. All unselected regions remain visible in the zone ledger.

Both barriers inside one OHLC bar are ambiguous. A favorable entry-bar extreme
is also ambiguous if entry was intrabar: that favorable extreme could precede
the touch. A gap opening beyond the far region edge is an ambiguous skipped
entry; no fill or successful touch is invented. Timeout and ambiguity remain
in the episode ledger but are excluded from the binary memory score. Pending
events cannot contribute future outcomes. A penetration stays in memory; the
price must return to the proper approach side before a new visit. This is an
event study, not a fill simulator or trade-profit calculation.

Each resolved bounce/penetration gets weight `2 ** (-age_bars / 60)`. With sums
`B` and `P`, the score is `(1 + B) / (2 + B + P)`. It is a smoothed **ranking
score, not a calibrated success probability**. Two distinct completed visits
are required before a zone is eligible for the nearest-side output. At most
three regions per side are ranked by score then ATR distance. The full ledger
retains zones without enough memory, retired zones and excluded outcomes, so
favorable selection is inspectable.

## Data discontinuities

A symmetric 1.5x change in open/previous-close or close/previous-close is a
**suspected** price discontinuity. Default policy returns
`unavailable_suspected_discontinuity` with no candidate zones. This heuristic
cannot prove a corporate action or validate adjusted OHLC. Legitimate large
market moves may also trigger it. Smaller bad adjustment transitions may escape
it; feed/basis certification is still required outside this component.

An explicit `discontinuity_policy="reset"` discards prior zone/ATR state and
requires a new 30-bar warm-up. Alternatively `reset_at` can contain exact aware
closed-bar timestamps for independently identified boundaries. Pending visits
are censored, never turned into false wins/losses. A reset is not a repaired
history and does not authorize mixing bases. No calendar gaps are inferred from
wall-clock intervals: weekends and exchange holidays require a certified market
calendar, not invented synthetic bars.

All output is labeled `research_only`, `production_validated=False` and
`unvalidated_on_corrected_feed=True`. These labels remain even when the caller's
price-basis name contains “adjusted”.

## Validation before any production change

1. Freeze the candidate code/hash, dataset hashes, price basis and corporate
   action boundaries before examining performance. Do not run a parameter grid.
2. The earlier 16-symbol, nine-variant pilot and already inspected 2024–2026
   test are development evidence. Reusing them is not a fresh holdout.
3. Choose unseen symbols without consulting outcomes; disclose current-universe
   survivorship. A new stock split across the same dates tests cross-sectional
   generalization, not a new market regime.
4. Use chronological partitions with a ten-bar purge at boundaries. Count all
   touches, ambiguities, timeouts and absent signals. Do not multiply one move
   into independent successes across overlapping regions.
5. Compare with the unchanged 120/3 baseline and random regions matched for
   side/date/ATR distance. An asymmetric 1 ATR versus 0.5 ATR event does not have
   a universal 50% chance benchmark. Report coverage as well as conditional
   bounce rate and 95% intervals preserving common dates/symbol dependence.
6. Confirm on forward paper observations after protocol freeze. A structural
   bounce result is not profitability. A separate realizable-entry trade study
   must include 7 bps commission per side, separate 0/5/10 bps slippage, opening
   gaps and the actual feasibility/costs of short positions.

Run deterministic causal tests from the repository root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -B -m unittest tests.test_atc_sr_zones
```

The tests use invented fixtures only. They verify confirmation timing, fixed
geometry, episode ordering and uncertainty, causal prefix invariance,
discontinuity guards, memory and metadata. Passing them does not establish an
economic advantage and does not promote this candidate to production.
