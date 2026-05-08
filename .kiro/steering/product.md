# Product: Intelligent Error Monitoring Agent

An AI-powered error monitoring agent that transforms raw production errors into actionable insights using semantic understanding.

## Core Capabilities

- **Semantic clustering** — groups similar errors by root cause, reducing noise (e.g. 20 errors → 4 clusters)
- **Context enrichment** — uses Airweave to find related code, Linear tickets, and Slack discussions
- **Smart suppression** — distinguishes NEW / REGRESSION / ONGOING errors to avoid duplicate alerts
- **Severity classification** — S1–S4 with reasoning
- **Integrations** — creates Linear tickets and posts Slack alerts; falls back to preview mode when not configured

## Data Sources

Supports `sample` (default demo data), `sentry`, `azure` (Log Analytics), and `datadog`.

## Modes

- **Demo mode** — sample data, mock Airweave results, preview Linear/Slack output (zero external dependencies)
- **Production mode** — real data sources, live integrations, scheduled or API-triggered runs

## Background

Based on an internal agent ("Donke") that handles ~40,000 Airweave queries/month. See `docs/ARCHITECTURE.md` for the full pipeline design.
