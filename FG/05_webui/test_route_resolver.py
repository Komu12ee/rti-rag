from services.route_resolver import resolve_route


TEST_CASES = [
    {
        "query": "पकराड़ी स्कूल का PIO कौन है?",
        "expected_route": "POSTGRES",
    },
    {
        "query": "RTI Act में धारा 8(1)(j) क्या है?",
        "expected_route": "QDRANT",
    },
    {
        "query": "बलरामपुर के PIO का नाम और RTI reply की time limit बताओ",
        "expected_route": "HYBRID",
    },
    {
        "query": "मुझे RTI के बारे में कुछ बताओ",
        "expected_route": "UNCLEAR",
    },
    {
        "query": "मुझे किसी office की जानकारी चाहिए",
        "expected_route": "UNCLEAR",
    },
]


def main() -> None:
    print("\n" + "=" * 95)
    print("ROUTER A + ROUTER B RESOLVER TEST")
    print("=" * 95)

    passed = 0

    for case in TEST_CASES:
        query = case["query"]
        expected_route = case["expected_route"]

        result = resolve_route(query)

        actual_route = result.final.route.value
        status = "PASS" if actual_route == expected_route else "CHECK"

        if status == "PASS":
            passed += 1

        print(f"\nQuery: {query}")
        print(f"Router A route:       {result.router_a.route.value}")
        print(f"Router A confidence:  {result.router_a.confidence}")
        print(f"LLM fallback used:    {result.used_llm_fallback}")
        print(f"Final route:          {actual_route}")
        print(f"Final confidence:     {result.final.confidence}")
        print(f"Final reason:         {result.final.reason}")
        print(f"Expected route:       {expected_route}")
        print(f"Status:               {status}")

    print("\n" + "=" * 95)
    print(f"Passed: {passed}/{len(TEST_CASES)}")
    print("=" * 95)


if __name__ == "__main__":
    main()