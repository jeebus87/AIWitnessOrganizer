# IRAC Prompt Revision Plan

## Research Summary

### Sources Consulted
1. Web search on IRAC best practices (2025)
2. [Columbia Law School IRAC/CRAC/CREAC Handout](https://www.law.columbia.edu/sites/default/files/2022-06/WC%20Handout%20IRAC,%20CRAC,%20CREAC.revised%205.22.pdf)
3. [LibreTexts Legal Synthesis - IRAC Writing Structure](https://biz.libretexts.org/Courses/Northeast_Wisconsin_Technical_College/Legal_Synthesis_and_Analysis_(Pless)/14:_Using_the_IRAC_Writing_Structure)
4. Gemini CLI consultation (gemini-2.5-pro)

### Key Insight: Academic IRAC vs. Practitioner IRAC
The critical distinction is that **academic IRAC** (law school exams) differs from **practitioner IRAC** (case briefs for working attorneys). Our system needs practitioner IRAC that provides **actionable legal intelligence**, not exam answers.

---

## Current Problems with Our IRAC Output

1. **ISSUE**: Often vague, not framed as a precise legal question
2. **RULE**: Sometimes too general, missing specific legal tests/elements
3. **APPLICATION**: Recites facts instead of explaining court's reasoning
4. **CONCLUSION**: Sometimes vague, doesn't directly answer the issue
5. **UTILITY**: Uses conditional language ("if you are alleging..."), not actionable

---

## Revised Component Guidelines

### 1. ISSUE - The Legal Question

**Purpose**: State the precise legal question the court answered. Allows attorney to do a "relevance check" in 5 seconds.

**Format Requirements**:
- Must be a QUESTION (use "Whether..." or "Does/Is...")
- Single sentence
- Combine legal question + key determinative facts
- Include jurisdiction/governing law

**Good Example**:
> "Whether a union breaches its duty of fair representation under California law when it refuses to arbitrate a member's grievance without conducting any investigation into the merits of the claim?"

**Bad Example**:
> "The issue is the duty of fair representation." (Not a question, no facts)

**Prompt Instruction**:
```
ISSUE: State the precise legal question as a single-sentence question starting with "Whether..."
Include: (1) the specific legal standard, (2) the key determinative facts, and (3) the jurisdiction.
Format: "Whether [legal standard] when [key facts that made this case unique]?"
```

---

### 2. RULE - The Legal Standard

**Purpose**: Provide the exact legal framework/test the court applied. This is the attorney's "ammunition" for their own motion.

**Format Requirements**:
- State the black-letter law clearly
- Quote verbatim from statutes/seminal cases (with citations)
- List elements if multi-factor test (numbered)
- Work from general principle to specific elements

**Good Example**:
> "Under California law, a union breaches its duty of fair representation when its conduct toward a member is 'arbitrary, discriminatory, or in bad faith.' (*Vaca v. Sipes*, 386 U.S. 171 (1967)). A union's actions are 'arbitrary' when they are: (1) without rational basis, (2) egregiously negligent, or (3) made without proper investigation. The six-month statute of limitations begins when the employee knew or should have known of the breach."

**Bad Example**:
> "The rule is that unions must represent members fairly." (Too vague, no test, no citation)

**Prompt Instruction**:
```
RULE: State the specific legal standard the court applied.
Include: (1) The governing statute or doctrine with citation, (2) The specific test or elements (numbered if multi-factor), (3) Any key definitions the court used.
Quote the exact legal language where possible.
```

---

### 3. APPLICATION - The Court's Reasoning (MOST IMPORTANT)

**Purpose**: Explain HOW and WHY the court applied the rule to reach its holding. This reveals the blueprint for persuasion.

**The Critical Distinction**:
| Weak (Fact Recitation) | Strong (Reasoning Explanation) |
|------------------------|-------------------------------|
| "The union refused to arbitrate. The employee filed suit. The court ruled for the employee." | "The court found the union breached its duty **because** it refused to arbitrate without any investigation. The court reasoned that the union's failure to interview witnesses or review documents demonstrated an 'arbitrary' disregard for the member's interests. The court emphasized that even a brief investigation would have revealed the grievance had substantial merit." |

**Format Requirements**:
- Use CAUSAL language: "because", "since", "the court reasoned that", "due to"
- Go element-by-element through the rule
- Explain WHY each fact mattered to the court
- Quote the court's own reasoning where available
- Explain why the losing party's arguments failed

**Prompt Instruction**:
```
APPLICATION: Explain the court's REASONING - WHY did the court rule as it did?

Structure your answer as:
1. "The court found [outcome] because..."
2. "The court reasoned that [specific logic]..."
3. "The decisive factors were: (1)..., (2)..., (3)..."
4. "The court rejected [losing party]'s argument that... because..."

Use causal language (because, since, therefore, due to). Do NOT just list facts - explain their legal significance and why they mattered to the court's analysis.
```

---

### 4. CONCLUSION - The Direct Answer

**Purpose**: One-sentence answer to the Issue. Tells attorney immediately if case is "for me" or "against me."

**Format Requirements**:
- Start with "Yes" or "No" (or "The court held...")
- Mirror the Issue but as a statement
- Include the key reasoning in brief

**Good Example**:
> "Yes, the court held the union breached its duty of fair representation because refusing to arbitrate without any investigation constitutes arbitrary conduct as a matter of law."

**Bad Example**:
> "The plaintiff won." (Doesn't answer the legal question)

**Prompt Instruction**:
```
CONCLUSION: Provide a direct answer to the Issue in one sentence.
Start with "Yes/No" or "The court held..."
Include the specific holding and key rationale.
```

---

### 5. UTILITY - Actionable Strategic Value (NEW APPROACH)

**Purpose**: Tell the attorney EXACTLY how to use this case. This is the most valuable section for practitioners.

**The Critical Change**: Use **command language**, not conditional language.

| Vague/Conditional (BAD) | Actionable/Command (GOOD) |
|-------------------------|---------------------------|
| "This case might be useful if you are alleging breach of duty." | "**Use this case to argue** that refusing to investigate a grievance before rejecting it is arbitrary conduct as a matter of law." |
| "If the plaintiff is bringing similar claims, this could be relevant." | "**Cite this case for the proposition** that unions cannot reject grievances without any factual investigation, regardless of their subjective belief in the claim's merit." |

**Format Requirements**:
- Use ACTION VERBS: "Argue...", "Use this case to...", "Cite for the proposition that...", "Distinguish by..."
- Provide specific argumentative language attorney can use
- Address both offensive and defensive uses
- Reference the attorney's specific case facts directly

**Prompt Instruction**:
```
UTILITY: Tell the attorney exactly how to use this case. Address them as "you."

Use command language:
- "Argue that..."
- "Use this case to support your position that..."
- "Cite this case for the proposition that..."
- "To distinguish this case, emphasize that..."

Be specific to their case: Reference their defendant ({defendant_name}), their allegations, and their legal theories. Do NOT use conditional language like "if you are alleging" or "this might be useful."

Structure:
1. **For Your Motion/Brief**: How to cite this case offensively
2. **Key Quote to Use**: A specific phrase or holding to quote
3. **Anticipate Opposition**: How opposing counsel might distinguish this case and how to respond
```

---

## Implementation Plan

### Phase 1: Update IRAC Prompt Structure

**File**: `app/services/legal_research_service.py`

**Changes to `analyze_case_irac_batch()` prompt**:

```python
prompt = f"""You are creating case briefs for a practicing attorney, not a law student.
Your goal is to provide ACTIONABLE legal intelligence they can use in motions and briefs.

YOUR CURRENT CASE:
- Case: {case_identifier}
- Defendant: {defendant_name}
- Allegations: {allegations_text}
- Legal Theories: {legal_theories}

CASES TO BRIEF:
{cases_text}

For EACH case, provide analysis in this format:

ISSUE: State the precise legal question as a single sentence starting with "Whether..."
- Include the specific legal standard and key determinative facts
- Example: "Whether a union breaches its duty of fair representation when it refuses to arbitrate a member's grievance without investigation?"

RULE: State the legal standard with specificity
- Quote the governing statute or test with citation
- List elements if multi-factor test (numbered)
- Example: "Under [cite], a union breaches its duty when its conduct is (1) arbitrary, (2) discriminatory, or (3) in bad faith."

APPLICATION: Explain the court's REASONING using causal language
- Structure: "The court found [outcome] BECAUSE..."
- Explain WHY each fact mattered: "The court emphasized that [fact] demonstrated [legal significance] because..."
- Include: "The decisive factors were: (1)..., (2)..., (3)..."
- Explain why losing arguments failed: "The court rejected [party]'s argument that... because..."
- Do NOT just list facts - explain their legal significance

CONCLUSION: Direct one-sentence answer
- Start with "Yes/No" or "The court held..."
- Mirror the Issue as a statement with key rationale

UTILITY: Tell the attorney EXACTLY how to use this case (address them as "you")
- Use ACTION VERBS: "Argue that...", "Cite for the proposition that...", "Use this case to support..."
- Be SPECIFIC to their case against {defendant_name}
- Provide a KEY QUOTE they can use in their brief
- Anticipate how opposing counsel might respond

JSON format:
{{
  "analyses": [
    {{
      "case_num": 1,
      "issue": "Whether [legal question with key facts]?",
      "rule": "[Specific legal standard with citation and elements]",
      "application": "The court found... BECAUSE... The court reasoned that... The decisive factors were...",
      "conclusion": "Yes/No, the court held [specific holding with rationale].",
      "utility": "Argue that... Cite this case for the proposition that... Key quote: '...' Anticipate..."
    }}
  ]
}}
```

### Phase 2: Add Legal Theories to Context

**File**: `app/api/v1/routes/legal_research.py`

Ensure `user_context` includes:
- `legal_theories`: List of identified legal theories from claims
- `defendant_name`: Extracted defendant name
- `case_identifier`: Full case name with number

### Phase 3: Testing Checklist

After implementation, verify each IRAC component:

- [ ] ISSUE is a question starting with "Whether..."
- [ ] ISSUE includes specific legal standard + key facts
- [ ] RULE quotes specific legal test with citation
- [ ] RULE lists elements if multi-factor test
- [ ] APPLICATION uses causal language ("because", "the court reasoned")
- [ ] APPLICATION explains WHY facts mattered, not just what they were
- [ ] APPLICATION addresses why losing arguments failed
- [ ] CONCLUSION starts with Yes/No or "The court held..."
- [ ] UTILITY uses action verbs ("Argue...", "Cite for...")
- [ ] UTILITY is specific to the attorney's case
- [ ] UTILITY includes a key quote to use
- [ ] NO conditional language ("if you are alleging", "might be useful")

---

## Example of Ideal Output

**Case**: Giffin v. United Transportation Union, 190 Cal. App. 3d 1359

**ISSUE**:
> "Whether a union member's breach of duty of fair representation claim is barred by a six-month statute of limitations when the member filed suit three and a half years after the union refused to arbitrate his grievance?"

**RULE**:
> "Under federal labor law, claims for breach of a union's duty of fair representation are subject to a six-month statute of limitations, borrowed from Section 10(b) of the National Labor Relations Act (29 U.S.C. § 160(b)). The limitations period begins to run when the employee knew or should have known of the union's alleged breach. (*DelCostello v. Int'l Bhd. of Teamsters*, 462 U.S. 151 (1983))."

**APPLICATION**:
> "The court found Giffin's claim time-barred **because** he waited more than three years after the union's refusal to arbitrate. The court reasoned that the six-month federal limitations period applies to hybrid Section 301/fair representation claims, and Giffin's filing was untimely by over three years. The decisive factors were: (1) Giffin knew of the union's refusal on August 12, 1981, (2) the limitations period expired in February 1982, and (3) he did not file until April 1985. The court rejected Giffin's argument that equitable tolling should apply **because** he presented no evidence of fraudulent concealment or extraordinary circumstances that would justify the extreme delay."

**CONCLUSION**:
> "Yes, the court held that Giffin's claim was barred by the six-month statute of limitations because he filed more than three years after he knew of the union's refusal to arbitrate."

**UTILITY**:
> "**For Your Defense**: Argue that any claims Munoz may have against Western States Regional Council of Carpenters for failure to represent him are time-barred if he did not file within six months of learning about the alleged breach. Cite this case for the proposition that the six-month federal limitations period applies strictly, even to state law claims arising from union representation failures.
>
> **Key Quote**: 'The six-month period of limitation... applies to actions by an employee against his union for breach of the duty of fair representation.'
>
> **Anticipate Opposition**: Munoz may argue equitable tolling based on ongoing harm or concealment. Respond by citing this case's rejection of tolling arguments absent extraordinary circumstances, emphasizing that Giffin's meritorious underlying claim did not excuse the three-year delay."

---

## Summary of Changes

| Component | Current Problem | Fix |
|-----------|----------------|-----|
| ISSUE | Often not a question | Must start with "Whether..." |
| RULE | Too vague | Require citation + elements |
| APPLICATION | Lists facts | Require causal language + reasoning |
| CONCLUSION | Vague | Must start Yes/No + mirror Issue |
| UTILITY | Conditional ("if...") | Command language ("Argue...") |
