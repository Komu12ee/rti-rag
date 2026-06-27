import app as web_app


TEST_CASES = [
    {
        "name": "Direct PIO lookup",
        "query": "पकराड़ी स्कूल का PIO कौन है?",
        "expected_query": "पकराड़ी स्कूल का PIO कौन है?",
        "expected_route": "POSTGRES",
        "expected_text": "राजा राम",
    },
    {
        "name": "Scoped old chat plus latest PIO question",
        "query": """
Previous conversation:
User: RTI Act में धारा 8(1)(j) क्या है?
Assistant: पुराना कानूनी उत्तर।

Current user question:
पकराड़ी स्कूल का PIO कौन है?
""",
        "expected_query": "पकराड़ी स्कूल का PIO कौन है?",
        "expected_route": "POSTGRES",
        "expected_text": "राजा राम",
    },
    {
        "name": "Unclear RTI question",
        "query": "मुझे RTI के बारे में कुछ बताओ",
        "expected_query": "मुझे RTI के बारे में कुछ बताओ",
        "expected_route": "UNCLEAR",
        "expected_text": "कृपया अपना प्रश्न",
    },
]


def main() -> None:
    print("\n" + "=" * 95)
    print("FLASK UNIFIED /api/query ENDPOINT TEST")
    print("=" * 95)

    passed = 0

    with web_app.app.test_client() as client:
        for case in TEST_CASES:
            response = client.post(
                "/api/query",
                json={
                    "query": case["query"],
                    "num_results": 3,
                },
            )

            payload = response.get_json() or {}

            answer = str(payload.get("answer", ""))

            ok = (
                response.status_code == 200
                and payload.get("success") is True
                and payload.get("query") == case["expected_query"]
                and payload.get("route") == case["expected_route"]
                and case["expected_text"] in answer
            )

            status = "PASS" if ok else "CHECK"

            if ok:
                passed += 1

            print(f"\nCase: {case['name']}")
            print(f"HTTP status: {response.status_code}")
            print(f"Success: {payload.get('success')}")
            print(f"Query returned: {payload.get('query')}")
            print(f"Route: {payload.get('route')}")
            print(f"Result count: {payload.get('result_count')}")
            print(f"Answer preview: {answer[:300]}")
            print(f"Status: {status}")

    print("\n" + "=" * 95)
    print(f"Passed: {passed}/{len(TEST_CASES)}")
    print("=" * 95)


if __name__ == "__main__":
    main()