# Job Compass

**AI-assisted job discovery and decision system for structured job evaluation, human review, and feedback-driven iteration.**

> Public portfolio build. It runs in Demo Mode with a synthetic dataset and is completely isolated from the private local system.

## Project Overview

Job Compass is a personal product project born from a real job-search problem: finding a job is not only a retrieval task. A candidate still needs to judge whether a role is eligible, aligned, worth the application effort, sufficiently documented, and consistent with personal constraints.

I defined the product requirements and decision logic, prioritized features, validated implementation, reviewed outputs, and decided iteration direction. Codex supported implementation; large language models supported requirement analysis and iteration discussion. AI did not independently define or build the product.

## Why I Built It

Real job discovery produces a fragmented and noisy decision environment:

- roles are scattered across multiple platforms;
- duplicate and expired postings compete for attention;
- JDs often omit salary, schedule, benefits, location details, or role scope;
- manual screening costs time but a single match score does not support a real application decision;
- a recommendation needs evidence and a reversible human review path.

The product reframes the problem from “Which JD looks similar to my resume?” to “Is this opportunity worth the next unit of application effort, and why?”

## Product Workflow

```text
Job Source / JD
        ↓
Parsing & Normalization
        ↓
Eligibility Check
        ↓
Multi-dimensional Scoring
        ↓
AI-assisted Recommendation
        ↓
Human Review
        ↓
Candidate Status & Feedback
        ↓
Rule Calibration
```

## Core Features

- Job collection configuration, normalization, source/run records, freshness and inactive-status management
- Multi-dimensional evaluation across Eligibility, Direction Fit, Career Value, Life Quality, Compensation and Opportunity Value
- Separate full-time and high-quality internship evaluation logic
- Risk levels, application recommendations, action priority and resume-track suggestions
- Explicit handling of missing information and questions requiring confirmation
- Manual review without overwriting the system score
- Candidate Status, status history and application Feedback
- Assessment history, rule-hit explanations, decision reasons and JD evidence
- Expired-job management and safe filtering from the daily action plan

## Human-in-the-loop Design

**AI recommendation ≠ final decision.**

The system proposes a structured recommendation, while the candidate keeps authority over whether to apply, how much effort to spend, and how to interpret context the rules cannot observe. Manual grades, comments, Candidate Status and Feedback remain distinct from system output so disagreement can become calibration evidence.

**Missing information ≠ negative evidence.**

Values such as:

```text
salary = not_disclosed
working_schedule = not_disclosed
five_insurances = not_disclosed
```

do not directly reduce role fit or opportunity value. They reduce information completeness and create questions for human confirmation. This prevents an unknown fact from being silently converted into a negative fact.

## Explainability

Each assessment retains four layers that can be inspected together:

- `score` — the numerical output for a dimension or overall decision;
- `rule hit` — the rule or signal that changed the score;
- `JD evidence` — the relevant text evidence used by the rule;
- `decision reason` — why the system recommends applying, tailoring, trying, confirming, or skipping.

Assessment history makes changes across rule versions visible rather than replacing earlier reasoning.

## Public Demo Safety

The public build is designed to fail closed:

- it accepts only `DEMO_MODE=true`;
- its SQLite URL must resolve to this repository's own `data/demo.db`;
- `demo.db` is generated on first startup from eight synthetic jobs in `app/demo_data.py`;
- the real crawler, source changes, imports, restores, deletes, reassessment and external API writes are blocked;
- Candidate Status, Feedback, manual review and “viewed” state may write only to the isolated Demo database;
- no private database, report, resume, application history, interview record, source configuration or secret is included.

## Demo Dataset

The eight fictional records demonstrate:

1. high match / priority application;
2. apply after resume customization;
3. low-cost application to validate an adjacent direction;
4. manual confirmation before deciding;
5. insufficient information without treating unknowns as negatives;
6. exclusion for a non-target location;
7. an expired role removed from the current action plan;
8. a high-quality internship evaluated with a separate framework.

All company names, JDs, evidence and workflow states in the Demo are fictional.

## Current Status

At a documented product milestone, the private system had produced around 70 job results, with 27 entering a confirmation workflow. It supports deleting expired roles. Job deduplication and external evidence enrichment remain under active iteration; these numbers are not presented as accuracy or efficiency claims.

## Product Decisions

- **Missing information ≠ negative evidence** — unknown fields affect confidence/completeness, not fit by default.
- **AI recommendation ≠ final decision** — the user controls the application decision and can record disagreement.
- **Explainability before full automation** — decision evidence and rule behavior are made inspectable before expanding automation.

## Tech Stack

- Python 3.12
- FastAPI and Uvicorn
- SQLAlchemy 2 with SQLite
- Pydantic / pydantic-settings
- Jinja2 server-rendered templates and native CSS
- PyYAML rule and profile configuration
- httpx-based collectors for public ATS sources in the private product (disabled in this Demo)
- pytest, Ruff and mypy for development checks

Dependencies are declared in `pyproject.toml`; there is no Node build step.

## Local Setup

From the `job-compass-public` directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe scripts\run_server.py
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001). Port 8001 is intentionally used so the public Demo does not collide with a private instance on port 8000.

The first startup creates `data/demo.db` and seeds synthetic data. Delete that generated file only if you intentionally want to reset the public Demo; it is ignored by Git.

## Screenshots

Screenshot placeholders and a privacy checklist are in [`docs/images/`](docs/images/README.md). Add only screenshots taken from this synthetic Demo:

<!-- ![Today action center](docs/images/01-daily-action-center.png) -->
<!-- ![Job list and scoring](docs/images/02-job-list-scoring.png) -->
<!-- ![Job detail dimensions](docs/images/03-job-detail-dimensions.png) -->
<!-- ![Explainability and JD evidence](docs/images/04-explainability-jd-evidence.png) -->
<!-- ![Human review and feedback](docs/images/05-human-review-feedback.png) -->
<!-- ![Missing information handling](docs/images/06-missing-information.png) -->

## Deployment Preparation

Render is the recommended first host because this is a conventional long-running FastAPI service with server-rendered templates and a writable Demo SQLite file. The included `render.yaml` uses:

```text
Build: pip install .
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health: /health
```

Render's [FastAPI guide](https://render.com/docs/deploy-fastapi) documents the same Uvicorn host/port pattern. Railway is also suitable for a long-running Python service. Vercel now supports FastAPI, but its function-oriented runtime is less natural for this Demo's mutable SQLite state; use it only after moving writable state to an external database. No deployment or repository creation is performed by this project preparation.

## Roadmap

- Improve job deduplication
- Introduce external employee/community feedback as auxiliary evidence
- Improve evidence confidence modeling
- Use human Feedback more systematically to calibrate scoring
- Continue hardening the public read-only Demo

## Repository Safety Checklist

Safe to publish: application code, synthetic seed code, public rule configuration, templates/static assets, `pyproject.toml`, `.env.example`, `.gitignore`, `render.yaml`, `.python-version`, documentation and Demo-only screenshots.

Never publish: `.env*` other than `.env.example`, any `*.db`/`*.sqlite*`, logs, backups, private reports, real resume/profile files, real source configuration, cookies/tokens, application/interview history, or screenshots from the private system.
