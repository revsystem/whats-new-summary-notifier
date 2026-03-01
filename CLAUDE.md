# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AWS CDK application that implements a Whats New Summary Notifier - a generative AI application that monitors RSS feeds (primarily AWS What's New and other tech blogs), summarizes content using Amazon Bedrock, and delivers notifications to Slack.

## Quick Start

```bash
npm install
npm run build
cdk bootstrap   # run once per account/region
cdk deploy
```

Prerequisites: Docker (required for Lambda build via `aws-lambda-python-alpha`). See [README.md](README.md) for full prerequisites.

## Architecture

The application consists of:
- RSS Crawler Lambda: Fetches RSS feeds and stores new entries in DynamoDB
- Notification Lambda: Triggered by DynamoDB streams, summarizes content using Bedrock, and posts to Slack
- DynamoDB Table: Stores RSS history to avoid duplicate processing
- EventBridge Rules: Schedules RSS crawling based on configured cron expressions
- SSM Parameter Store: Securely stores Slack webhook URLs

## Key Files

- `bin/whats-new-summary-notifier.ts` - CDK app entry point
- `lib/whats-new-summary-notifier-stack.ts` - Stack definition (DynamoDB, Lambdas, EventBridge, SSM)
- `cdk.json` - Application configuration (modelRegion, modelId, summarizers, notifiers)

## Build and Development Commands

### CDK Operations
- `cdk bootstrap` - Initialize CDK in the AWS account/region (run once)
- `cdk synth` - Synthesize CloudFormation templates and verify configuration
- `cdk deploy` - Deploy the stack to AWS
- `cdk destroy` - Delete the stack from AWS

### Code Quality
- `npm run build` - Compile TypeScript to JavaScript
- `npm run watch` - Watch for TypeScript changes and compile automatically
- `npm test` - Run Jest tests
- `ruff check` - Lint Python code in Lambda functions
- `ruff format` - Format Python code in Lambda functions
- `npx eslint .` - Run ESLint on TypeScript code (uses eslint.config.mjs)
- `npm run audit` - Run npm security audit on dependencies
- `npm run deps:update` - Update dependencies, then build and test

## Lambda Functions

### RSS Crawler (`lambda/rss-crawler/index.py`)
- Fetches RSS feeds using feedparser
- Filters entries to only those published within the last 7 days (hardcoded)
- Stores new entries in DynamoDB

### Notification Handler (`lambda/notify-to-app/index.py`)
- Triggered by DynamoDB streams on new RSS entries
- Scrapes full article content using cloudscraper and BeautifulSoup (targets `<main>` tag)
- Summarizes content using Strands Agents SDK with Bedrock
- Posts formatted messages to Slack with Twitter sharing links

## Development Notes

- Python Lambda functions use Python 3.12 runtime
- CDK stack uses TypeScript with AWS CDK v2
- Tool versions are managed via `mise` (see `mise.toml`) — install with `mise install`
- Web scraping handles Cloudflare protection using cloudscraper

## Architecture and Security Constraints

See `.claude/rules/` for detailed constraints Claude must follow:
- `.claude/rules/architecture-patterns.md` — DynamoDB design, Lambda concurrency limit, Bedrock params, F1 glossary
- `.claude/rules/security-requirements.md` — CDK nag, SSM secrets, IAM
- `.claude/rules/infrastructure-requirements.md` — AWS profiles, CDK context values, SSM parameter names

## Deployment

See `.claude/skills/deploy-production/SKILL.md` or invoke `/deploy-production` for the full deployment checklist including WSL2 setup, CDK deploy, and post-deploy verification.
