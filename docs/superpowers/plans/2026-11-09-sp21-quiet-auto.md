# SP21 Quiet Auto Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** In Auto mode the only question is whether to raise a loop limit, and no gate holds up an independent ticket.

**Spec:** `docs/superpowers/specs/2026-11-09-sp21-quiet-auto-design.md`

- [x] `workflow`: token grant at the cap, stalls become the loop-limit gate.
- [x] `relay._recover`: failed tickets and unfinished merges.
- [x] `Context.auto`; skills `plan`, `grill`, `loop` and `events.md`.
- [x] Tests in `tests/test_sp21_quiet_auto.py`.
