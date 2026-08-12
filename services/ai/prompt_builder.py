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
Analyze the following anonymised loan profile, business details, loan summary, and repayment history of a merchant.
You need to suggest a recommended loan amount and evaluate creditworthiness.

CRITICAL GUARDRAIL POLICIES:
- The backend has calculated the current deterministic range from the merchant's loan history using its Python policy. The calculated minimum is E{python_floor} and maximum/ceiling is E{python_ceiling}.
- Do not use the persisted customer.credit_score as the loan limit; it is only a legacy cached field and may be stale.
- The absolute upper cap (giving cushion room for growth) is set at E{gemini_cap}.
- Your proposed 'suggested_loan_amount' MUST be a number, and MUST NOT exceed the absolute cap of E{gemini_cap}.
- Suggest a defensible amount from E{python_floor} up to E{gemini_cap}. You may recommend below the deterministic ceiling when the profile supports a smaller safe amount. Use the buffer above E{python_ceiling} only when a concrete, evidenced opportunity justifies it.

LOCAL CONTEXT CONSIDERATIONS:
- The merchant's location is: {merchant_location}.
- Research and look up any notable local town events, holidays, market days, or seasonal business opportunities near this location that could affect customer traffic.
- Incorporate these location-specific insights or upcoming events as positive/negative signals in your loan evaluation. Any events or location factors used must be listed explicitly in your "reasons" list.
- Use the supplied business type, revenue, expenses, cash flow, tenure, employees, and loan purpose as evidence. Do not invent a credit score; it is an internal limit only.

MERCHANT PROFILE:
{profile}

LOAN SUMMARY:
{loan_summary}

REPAYMENT SUMMARY:
{repayment_summary}

Return JSON with exactly these fields. Use this exact JSON structure as your template:
{{
  "explanation": "Your extremely concise, professional plain-language summary (strictly limited to 2-3 sentences max) explaining the merchant's situation, reasoning for suggested loan amount, and local context used.",
  "risk_summary": "low",
  "suggested_loan_amount": 250.0,
  "confidence": 95,
  "reasons": ["repayment history reason", "location context reason with local event details"],
  "strengths": ["strength1"],
  "weaknesses": ["weakness1"]
}}
Note: Under 'risk_summary' you can output either 'low', 'medium', or 'high'. Under 'suggested_loan_amount' you must output a raw number (e.g. 500.0) that must not exceed E{gemini_cap} and should normally be at least E{python_floor} unless the merchant is high risk or blacklisted.
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
        python_floor = profile.get('deterministic_floor', 200)
        python_ceiling = profile.get('deterministic_ceiling', 500)
        gemini_cap = profile.get('gemini_absolute_cap', 575)
        merchant_location = profile.get('merchant_location', 'Unknown')
        
        return PromptBuilder.LOAN_ADVISOR_PROMPT.format(
            python_floor=python_floor,
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
