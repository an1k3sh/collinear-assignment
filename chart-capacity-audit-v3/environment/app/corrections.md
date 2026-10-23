# Export desk notes

The export batch is not a collection of additive observations.

* **C2.r2 replaces the entire C2.r1 page.** The old Birch error-counter series
  included retry-attempt accounting. The correction fixes that metric. Request
  counters are repeated for context, not additional requests.
* Other pages remain authoritative. Revision numbers are per logical page:
  C1.r1 is not obsolete merely because C2 has an r2.
* In C4, Delta Query API's B2 traffic telemetry was lost. The chart's UNKNOWN
  marker is not a measured zero. The operations log documents a zero-baseline
  reset at the beginning of W3, which may allow that later window to be
  reconstructed without the missing pre-reset B2 sample.
* Samples at a reset boundary are the final samples of the OLD epoch. A reset
  in operations.json takes place immediately AFTER that sample, at the start
  of the named window. End-of-window samples are from the new epoch.

These are authority and instrument-semantics notes, not corrected raw data.
The values must still be read from the authoritative images.
