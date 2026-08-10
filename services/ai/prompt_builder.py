class PromptBuilder:
    """Central prompt template repository. No duplicated prompts."""

    LOAN_ADVISOR_SYSTEM = (
        "You are Qinance's AI Loan Advisor for microfinance agents. "
        "You provide advisory explanations ONLY. You NEVER approve or reject loans. "
        "All financial decisions are made by the backend business rules. "
        "Always explain WHY in your recommendations. "
        "Return responses as valid JSON only."
    )

    LOAN_ADVISOR_PROMPT = """
Analyze the following anonymised loan profile, loan summary, and repayment history of a merchant.
You need to suggest a recommended loan amount and evaluate creditworthiness.

CRITICAL GUARDRAIL POLICIES:
- Note: 'credit_score' is a scoring metric (NOT a cash credit limit). 
- The deterministic Python ceiling is set at E{python_ceiling}.
- The absolute upper cap is set at E{gemini_cap}.
- Your proposed 'suggested_loan_amount' MUST be a number, and MUST NOT exceed the absolute cap of E{gemini_cap}.
- Suggest a reasonable amount within the E{python_ceiling} to E{gemini_cap} range (e.g. if python_ceiling is E500, suggest something like E500 to E575, never suggest E3000+).

LOCAL CONTEXT CONSIDERATIONS:
- The merchant's location is: {merchant_location}.
- Research and look up any notable local town events, holidays, market days, or seasonal business opportunities near this location that could affect customer traffic.
- Incorporate these location-specific insights or upcoming events as positive/negative signals in your loan evaluation. Any events or location factors used must be listed explicitly in your "reasons" list.

MERCHANT PROFILE:
{profile}

LOAN SUMMARY:
{loan_summary}

REPAYMENT SUMMARY:
{repayment_summary}

Return JSON with exactly these fields:
{{
  "explanation": "Extremely concise, professional plain-language summary (strictly limited to 2-3 sentences max) explaining the merchant's situation, reasoning for suggested loan amount, and local context used.",
  "risk_summary": "low|medium|high",
  "suggested_loan_amount": number (MUST NOT exceed E{gemini_cap}),
  "confidence": number (0-100),
  "reasons": ["reason1 incorporating local context/events", "reason2"],
  "strengths": ["strength1"],
  "weaknesses": ["weakness1"]
}}
"""

    BUSINESS_HEALTH_SYSTEM = (
        "You are Qinance's AI Business Advisor. "
        "You provide advisory insights only. You never make financial decisions. "
        "Always explain WHY. Return responses as valid JSON only."
    )

    BUSINESS_HEALTH_PROMPT = """
Analyze the following merchant business summary and generate a business health score.

BUSINESS SUMMARY:
{summary}

Return JSON with exactly these fields:
{{
  "business_health": number (0-100),
  "health_label": "Excellent|Good|Average|Needs Attention",
  "risk": "low|medium|high",
  "confidence": number (0-100),
  "strengths": ["strength1"],
  "weaknesses": ["weakness1"],
  "recommended_actions": ["action1"],
  "explanation": "Why this score was given"
}}
"""

    @staticmethod
    def build_loan_advisor_prompt(profile_json, loan_summary, repayment_summary):
        import json
        profile = json.loads(profile_json)
        python_ceiling = profile.get('deterministic_ceiling', 500)
        gemini_cap = profile.get('gemini_absolute_cap', 575)
        merchant_location = profile.get('merchant_location', 'Unknown')
        
        return PromptBuilder.LOAN_ADVISOR_PROMPT.format(
            python_ceiling=python_ceiling,
            gemini_cap=gemini_cap,
            merchant_location=merchant_location,
            profile=profile_json,
            loan_summary=loan_summary,
            repayment_summary=repayment_summary
        )

    @staticmethod
    def build_business_health_prompt(summary):
        return PromptBuilder.BUSINESS_HEALTH_PROMPT.format(summary=summary)