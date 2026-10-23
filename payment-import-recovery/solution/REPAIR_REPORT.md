# Repair

Equal amounts/timestamps are not payment identity. Keys now include tenant and
payment ID; text invoice identifiers retain leading zeros. Integer decimal
parsing avoids float truncation. Payment and original receipt commit together
under a write lock; a post-commit transport failure is safely retryable.

Worker outcomes are collected in input order, failures are explicit, and the
CLI returns nonzero if any row failed. Each good row remains committed.
The incident export was replayed without modifying the original receipt.
Validation: `python -m unittest discover -s tests`; external concurrency and
fault-injection checks exercise the same public interface.
