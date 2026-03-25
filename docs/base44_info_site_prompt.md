Build a polished public-facing information website for FancyFinance.

This is not the trading app itself.
This is not the internal dashboard.
This is not the Telegram bot implementation.
It is a marketing and information site that explains the FancyFinance ecosystem clearly and sends users into the Telegram bot.

Main goal:
Create a premium fintech product site that explains what FancyFinance is, how it works, how the user journey works, how subscriptions work, and why the product is credible.

Primary CTA:
Send users to the Telegram bot.

Product context:
FancyFinance is a Telegram-first algorithmic trading platform with:
- Telegram bot onboarding and controls
- Railway-hosted Python backend
- FastAPI control plane
- Supabase persistence
- Stripe subscriptions for paid membership
- n8n-powered email verification delivery
- backtesting, simulation, and live workflows
- secure API key storage
- browser-based dashboard and control center
- Phemex integration

Business model:
- Free plan: backtesting, onboarding, email verification
- Pro plan: $6.99/month
- Pro includes: simulation mode, live mode, secure API key storage, dashboard/control access
- Stripe powers paid subscriptions

What the site should communicate:
1. FancyFinance is controlled through Telegram first.
2. The backend runs on Railway.
3. Supabase stores user, config, position, and trade state.
4. Stripe manages paid subscriptions.
5. n8n handles email verification delivery.
6. Backtesting is free.
7. Simulation and live trading require Pro at $6.99/month.
8. Live trading carries real risk.
9. FancyFinance is educational software, not financial advice.

Main sections to include:

1. Hero
- strong premium fintech headline
- subheadline explaining Telegram-first trading control
- CTA: Start on Telegram
- secondary CTA: How It Works

2. What FancyFinance Is
- clear explanation of the product
- explain that it combines Telegram control, backend automation, secure storage, and monitoring

3. How It Works
- Open the Telegram bot
- Review disclosure and create account
- Verify email
- Choose plan
- Upgrade with Stripe if needed
- Store exchange API keys
- Run in simulation or live mode
- Monitor through Telegram and dashboard

4. Plans
- Free
  - Backtesting
  - Telegram onboarding
  - Email verification
- Pro — $6.99/month
  - Simulation mode
  - Live trading mode
  - Secure API key storage
  - Dashboard access
  - Control features

5. Features
- Telegram-first controls
- Fast setup
- backtesting
- simulation mode
- live mode
- secure API key storage
- persistent account state
- dashboard visibility
- operational controls

6. Security / Trust / Risk
- educational software only
- no guaranteed profits
- users control their own exchange credentials
- transparent risk disclosure
- secure handling of stored account data
- subscription billing handled by Stripe

7. Architecture Overview
Explain the stack at a high level:
- marketing site
- Telegram bot
- Railway backend
- FastAPI control layer
- Supabase
- Stripe billing
- n8n email verification
- exchange connectivity

8. System Flow
Show the user journey:
- Site -> Telegram
- Telegram -> account setup
- email verification
- membership gating
- Stripe checkout
- API setup
- simulation/live workflow
- dashboard monitoring

9. Final CTA
- strong Telegram CTA
- direct users into the bot

Style direction:
- premium fintech
- modern and credible
- not scammy
- not crypto-bro
- not generic AI template
- strong typography
- clean spacing
- strong hierarchy
- responsive on desktop and mobile

Tone:
- trustworthy
- modern
- product-focused
- clear
- transparent
- confident but not hypey

Content rules:
- do not claim guaranteed profits
- do not exaggerate AI capabilities
- do not imply custody of user funds
- do not present FancyFinance as financial advice
- keep messaging honest and product-accurate

Use this product flow as the source of truth:
- User opens the marketing site
- User clicks into the Telegram bot
- User starts onboarding
- User verifies email
- Free users get backtesting only
- Pro users at $6.99/month get simulation and live access
- Stripe checkout upgrades users to Pro
- Users can store API keys and operate through Telegram and the dashboard

Main CTA destination:
[PUT TELEGRAM BOT LINK HERE]
