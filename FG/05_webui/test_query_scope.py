from services.query_scope import extract_current_user_question


TEST_CASES = [
    {
    "name": "Actual browser scoped payload",
    "input": """
Current user question: पकराड़ी स्कूल का PIO कौन है?

Recent conversation context:
User: tell me name and email of FAA officer in balod district
Assistant: कोई रिकॉर्ड नहीं मिला।

Assistant role and answer scope:
Provide RTI assistance only.
""",
    "expected": "पकराड़ी स्कूल का PIO कौन है?",
},  
    {
        "name": "Direct question",
        "input": "पकराड़ी स्कूल का PIO कौन है?",
        "expected": "पकराड़ी स्कूल का PIO कौन है?",
    },
    {
        "name": "Scoped officer question",
        "input": """
Previous conversation:
User: RTI Act में धारा 8(1)(j) क्या है?
Assistant: यह RTI Act की एक धारा है।

Current user question:
पकराड़ी स्कूल का PIO कौन है?
""",
        "expected": "पकराड़ी स्कूल का PIO कौन है?",
    },
    {
        "name": "Scoped hybrid question",
        "input": """
Recent conversation:
User: मुझे RTI के बारे में कुछ बताओ।
Assistant: कृपया प्रश्न स्पष्ट करें।

Current user question:
बलरामपुर के PIO का नाम और RTI reply की time limit बताओ
""",
        "expected": "बलरामपुर के PIO का नाम और RTI reply की time limit बताओ",
    },
    {
        "name": "Lowercase marker",
        "input": """
Chat context:
User: पुराना प्रश्न

current user question: RTI में first appeal कैसे करें?
""",
        "expected": "RTI में first appeal कैसे करें?",
    },
]


def main() -> None:
    print("\n" + "=" * 90)
    print("CURRENT USER QUESTION EXTRACTION TEST")
    print("=" * 90)

    passed = 0

    for case in TEST_CASES:
        actual = extract_current_user_question(case["input"])
        status = "PASS" if actual == case["expected"] else "CHECK"

        if status == "PASS":
            passed += 1

        print(f"\nCase: {case['name']}")
        print(f"Expected: {case['expected']}")
        print(f"Actual:   {actual}")
        print(f"Status:   {status}")

    print("\n" + "=" * 90)
    print(f"Passed: {passed}/{len(TEST_CASES)}")
    print("=" * 90)


if __name__ == "__main__":
    main()
