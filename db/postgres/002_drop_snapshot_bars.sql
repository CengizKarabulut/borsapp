-- canonical_market_bars is the single OHLCV source. Snapshots only describe
-- immutable windows and no runtime code reads or writes canonical_bars.
DROP TABLE IF EXISTS canonical_bars;
