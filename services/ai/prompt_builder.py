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
- Deterministic Python ceiling is set at E{python_ceiling}.
- Gemini absolute upper cap is set at E{gemini_cap}.
- Your proposed suggested_loan_amount MUST be a number, and MUST NOT exceed the absolute cap of E{gemini_cap}.
- Evaluate if the merchant should receive up to the absolute cap, or a lower amount based on their credit risk.

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
  "explanation": "Plain-language explanation of the merchant's situation, reasoning for suggested loan amount, and location context",
  "risk_summary": "low|medium|high",
  "suggested_loan_amount": number (MUST NOT exceed gemini_absolute_cap),
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